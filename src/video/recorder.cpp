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

    bool Recorder::Init(
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

    void Recorder::Destroy() {
        Recorder *recorder = this;
        SDL_DestroyCond(recorder->queue_cond);
        SDL_DestroyMutex(recorder->mutex);
        SDL_free(recorder->filename);
    }


    bool Recorder::Open(const AVCodec *input_codec) {
        Recorder *recorder = this;
        const char *format_name = RecorderGetFormatName(recorder->format);
        assert(format_name);
        const AVOutputFormat *format = FindMuxer(format_name);
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

    void Recorder::Close() {
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
            const char *format_name = RecorderGetFormatName(recorder->format);
            LOGI("Recording complete to %s file: %s", format_name, recorder->filename);
        }
    }

    bool Recorder::WriteHeader(const AVPacket *packet) {
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

    void Recorder::RescalePacket(AVPacket *packet) {
        Recorder *recorder = this;
        AVStream *ostream = recorder->ctx->streams[0];
        av_packet_rescale_ts(packet, SCRCPY_TIME_BASE, ostream->time_base);
    }

    bool Recorder::Write(AVPacket *packet) {
        Recorder *recorder = this;
        if (!recorder->header_written) {
            if (packet->pts != AV_NOPTS_VALUE) {
                LOGE("The first packet is not a config packet");
                return false;
            }
            bool ok = recorder->WriteHeader(packet);
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

        recorder->RescalePacket(packet);
        return av_write_frame(recorder->ctx, packet) >= 0;
    }

    int Recorder::RunRecorder(void *data) {
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
                    bool ok = recorder->Write(&last->packet);
                    if (!ok) {
                        // failing to write the last frame is not very serious, no
                        // future frame may depend on it, so the resulting file
                        // will still be valid
                        LOGW("Could not record last packet");
                    }
                    RecordPacketDelete(last);
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

            bool ok = recorder->Write(&previous->packet);
            RecordPacketDelete(previous);
            if (!ok) {
                LOGE("Could not record packet");

                util::mutex_lock(recorder->mutex);
                recorder->failed = true;
                // discard pending packets
                RecorderQueueClear(&recorder->queue);
                util::mutex_unlock(recorder->mutex);
                break;
            }

        }

        LOGD("Recorder thread ended");

        return 0;
    }

    bool Recorder::Start() {
        LOGD("Starting recorder thread");
        Recorder *recorder = this;
        recorder->thread = SDL_CreateThread(RunRecorder, "recorder", recorder);
        if (!recorder->thread) {
            LOGC("Could not start recorder thread");
            return false;
        }

        return true;
    }

    void Recorder::Stop() {
        Recorder *recorder = this;
        util::mutex_lock(recorder->mutex);
        recorder->stopped = true;
        util::cond_signal(recorder->queue_cond);
        util::mutex_unlock(recorder->mutex);
    }

    void Recorder::Join() {
        Recorder *recorder = this;
        SDL_WaitThread(recorder->thread, nullptr);
    }

    bool Recorder::Push(const AVPacket *packet) {
        Recorder *recorder = this;
        util::mutex_lock(recorder->mutex);
        assert(!recorder->stopped);

        if (recorder->failed) {
            // reject any new packet (this will stop the stream)
            return false;
        }

        struct RecordPacket *rec = RecordPacketNew(packet);
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