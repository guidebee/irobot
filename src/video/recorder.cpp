//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "recorder.hpp"

#include <cassert>
#include "config.hpp"

#include "util/lock.hpp"
#include "util/log.hpp"

namespace irobot::video {

    static const AVRational SCRCPY_TIME_BASE = {1, 1000000}; // timestamps in us

    bool Recorder::init(
            const char *filename,
            enum RecordFormat format,
            struct Size declared_frame_size) {
        Recorder *recorder = this;
        recorder->filename = SDL_strdup(filename);
        if (!recorder->filename) {
            LOGE("Could not strdup filename");
            return false;
        }

        recorder->mutex = SDL_CreateMutex();
        if (!recorder->mutex) {
            LOGC("Could not create mutex");
            SDL_free(recorder->filename);
            return false;
        }

        recorder->queue_cond = SDL_CreateCond();
        if (!recorder->queue_cond) {
            LOGC("Could not create cond");
            SDL_DestroyMutex(recorder->mutex);
            SDL_free(recorder->filename);
            return false;
        }

        queue_init(&recorder->queue);
        recorder->stopped = false;
        recorder->failed = false;
        recorder->format = format;
        recorder->declared_frame_size = declared_frame_size;
        recorder->header_written = false;
        recorder->previous = nullptr;

        return true;
    }

    void Recorder::destroy() {
        Recorder *recorder = this;
        SDL_DestroyCond(recorder->queue_cond);
        SDL_DestroyMutex(recorder->mutex);
        SDL_free(recorder->filename);
    }


    bool Recorder::open(const AVCodec *input_codec) {
        Recorder *recorder = this;
        const char *format_name = recorder_get_format_name(recorder->format);
        assert(format_name);
        const AVOutputFormat *format = find_muxer(format_name);
        if (!format) {
            LOGE("Could not find muxer");
            return false;
        }

        recorder->ctx = avformat_alloc_context();
        if (!recorder->ctx) {
            LOGE("Could not allocate output context");
            return false;
        }

        // contrary to the deprecated API (av_oformat_next()), av_muxer_iterate()
        // returns (on purpose) a pointer-to-const, but AVFormatContext.oformat
        // still expects a pointer-to-non-const (it has not be updated accordingly)
        // <https://github.com/FFmpeg/FFmpeg/commit/0694d8702421e7aff1340038559c438b61bb30dd>
        recorder->ctx->oformat = (AVOutputFormat *) format;

        av_dict_set(&recorder->ctx->metadata, "comment",
                    "Recorded by scrcpy "
                    SCRCPY_VERSION, 0);

        AVStream *ostream = avformat_new_stream(recorder->ctx, input_codec);
        if (!ostream) {
            avformat_free_context(recorder->ctx);
            return false;
        }


        ostream->codecpar->codec_type = AVMEDIA_TYPE_VIDEO;
        ostream->codecpar->codec_id = input_codec->id;
        ostream->codecpar->format = AV_PIX_FMT_YUV420P;
        ostream->codecpar->width = recorder->declared_frame_size.width;
        ostream->codecpar->height = recorder->declared_frame_size.height;


        int ret = avio_open(&recorder->ctx->pb, recorder->filename,
                            AVIO_FLAG_WRITE);
        if (ret < 0) {
            LOGE("Failed to open output file: %s", recorder->filename);
            // ostream will be cleaned up during context cleaning
            avformat_free_context(recorder->ctx);
            return false;
        }

        LOGI("Recording started to %s file: %s", format_name, recorder->filename);

        return true;
    }

    void Recorder::close() {
        Recorder *recorder = this;
        if (recorder->header_written) {
            int ret = av_write_trailer(recorder->ctx);
            if (ret < 0) {
                LOGE("Failed to write trailer to %s", recorder->filename);
                recorder->failed = true;
            }
        } else {
            // the recorded file is empty
            recorder->failed = true;
        }
        avio_close(recorder->ctx->pb);
        avformat_free_context(recorder->ctx);

        if (recorder->failed) {
            LOGE("Recording failed to %s", recorder->filename);
        } else {
            const char *format_name = recorder_get_format_name(recorder->format);
            LOGI("Recording complete to %s file: %s", format_name, recorder->filename);
        }
    }

    bool Recorder::write_header(const AVPacket *packet) {
        Recorder *recorder = this;
        AVStream *ostream = recorder->ctx->streams[0];

        auto *extradata = static_cast<uint8_t *>(av_malloc(packet->size * sizeof(uint8_t)));
        if (!extradata) {
            LOGC("Could not allocate extradata");
            return false;
        }

        // copy the first packet to the extra data
        memcpy(extradata, packet->data, packet->size);

        ostream->codecpar->extradata = extradata;
        ostream->codecpar->extradata_size = packet->size;


        int ret = avformat_write_header(recorder->ctx, nullptr);
        if (ret < 0) {
            LOGE("Failed to write header to %s", recorder->filename);
            return false;
        }

        return true;
    }

    void Recorder::rescale_packet(AVPacket *packet) {
        Recorder *recorder = this;
        AVStream *ostream = recorder->ctx->streams[0];
        av_packet_rescale_ts(packet, SCRCPY_TIME_BASE, ostream->time_base);
    }

    bool Recorder::write(AVPacket *packet) {
        Recorder *recorder = this;
        if (!recorder->header_written) {
            if (packet->pts != AV_NOPTS_VALUE) {
                LOGE("The first packet is not a config packet");
                return false;
            }
            bool ok = recorder->write_header(packet);
            if (!ok) {
                return false;
            }
            recorder->header_written = true;
            return true;
        }

        if (packet->pts == AV_NOPTS_VALUE) {
            // ignore config packets
            return true;
        }

        recorder->rescale_packet(packet);
        return av_write_frame(recorder->ctx, packet) >= 0;
    }

    int Recorder::run_recorder(void *data) {
        auto *recorder = static_cast<struct Recorder *>(data);

        for (;;) {
            util::mutex_lock(recorder->mutex);

            while (!recorder->stopped && queue_is_empty(&recorder->queue)) {
                util::cond_wait(recorder->queue_cond, recorder->mutex);
            }

            // if stopped is set, continue to process the remaining events (to
            // finish the recording) before actually stopping

            if (recorder->stopped && queue_is_empty(&recorder->queue)) {
                util::mutex_unlock(recorder->mutex);
                struct RecordPacket *last = recorder->previous;
                if (last) {
                    // assign an arbitrary duration to the last packet
                    last->packet.duration = 100000;
                    bool ok = recorder->write(&last->packet);
                    if (!ok) {
                        // failing to write the last frame is not very serious, no
                        // future frame may depend on it, so the resulting file
                        // will still be valid
                        LOGW("Could not record last packet");
                    }
                    record_packet_delete(last);
                }
                break;
            }

            struct RecordPacket *rec;
            queue_take(&recorder->queue, next, &rec);

            util::mutex_unlock(recorder->mutex);

            // recorder->previous is only written from this thread, no need to lock
            struct RecordPacket *previous = recorder->previous;
            recorder->previous = rec;

            if (!previous) {
                // we just received the first packet
                continue;
            }

            // config packets have no PTS, we must ignore them
            if (rec->packet.pts != AV_NOPTS_VALUE
                && previous->packet.pts != AV_NOPTS_VALUE) {
                // we now know the duration of the previous packet
                previous->packet.duration = rec->packet.pts - previous->packet.pts;
            }

            bool ok = recorder->write(&previous->packet);
            record_packet_delete(previous);
            if (!ok) {
                LOGE("Could not record packet");

                util::mutex_lock(recorder->mutex);
                recorder->failed = true;
                // discard pending packets
                recorder_queue_clear(&recorder->queue);
                util::mutex_unlock(recorder->mutex);
                break;
            }

        }

        LOGD("Recorder thread ended");

        return 0;
    }

    bool Recorder::start() {
        LOGD("Starting recorder thread");
        Recorder *recorder = this;
        recorder->thread = SDL_CreateThread(run_recorder, "recorder", recorder);
        if (!recorder->thread) {
            LOGC("Could not start recorder thread");
            return false;
        }

        return true;
    }

    void Recorder::stop() {
        Recorder *recorder = this;
        util::mutex_lock(recorder->mutex);
        recorder->stopped = true;
        util::cond_signal(recorder->queue_cond);
        util::mutex_unlock(recorder->mutex);
    }

    void Recorder::join() {
        Recorder *recorder = this;
        SDL_WaitThread(recorder->thread, nullptr);
    }

    bool Recorder::push(const AVPacket *packet) {
        Recorder *recorder = this;
        util::mutex_lock(recorder->mutex);
        assert(!recorder->stopped);

        if (recorder->failed) {
            // reject any new packet (this will stop the stream)
            return false;
        }

        struct RecordPacket *rec = record_packet_new(packet);
        if (!rec) {
            LOGC("Could not allocate record packet");
            return false;
        }

        queue_push(&recorder->queue, next, rec);
        util::cond_signal(recorder->queue_cond);

        util::mutex_unlock(recorder->mutex);
        return true;
    }

}