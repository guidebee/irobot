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

    static const AVRational IROBOT_TIME_BASE = {1, 1000000}; // timestamps in us

    bool Recorder::Init(
            const char *filename,
            enum RecordFormat format,
            struct Size declared_frame_size) {

        this->filename = SDL_strdup(filename);
        if (!this->filename) {
            LOGE("Could not strdup filename");
            return false;
        }

        this->mutex = SDL_CreateMutex();
        if (!this->mutex) {
            LOGC("Could not create mutex");
            SDL_free(this->filename);
            return false;
        }

        this->thread_cond = SDL_CreateCond();
        if (!this->thread_cond) {
            LOGC("Could not create cond");
            SDL_DestroyMutex(this->mutex);
            SDL_free(this->filename);
            return false;
        }

        queue_init(&this->queue);
        this->stopped = false;
        this->failed = false;
        this->format = format;
        this->declared_frame_size = declared_frame_size;
        this->header_written = false;
        this->previous = nullptr;

        return true;
    }

    void Recorder::Destroy() {
        Actor::Destroy();
        SDL_free(this->filename);
    }

    void Recorder::RecordPacketDelete(struct RecordPacket *rec) {
        av_packet_unref(&rec->packet);
        SDL_free(rec);
    }

    void Recorder::RecorderQueueClear(struct RecordQueue *queue) {
        while (!queue_is_empty(queue)) {
            struct RecordPacket *rec;
            queue_take(queue, next, &rec);
            RecordPacketDelete(rec);
        }
    }

    const char *Recorder::RecorderGetFormatName(enum RecordFormat format) {
        switch (format) {
            case RECORDER_FORMAT_MP4:
                return "mp4";
            case RECORDER_FORMAT_MKV:
                return "matroska";
            default:
                return nullptr;
        }
    }

    RecordPacket *Recorder::RecordPacketNew(const AVPacket *packet) {
        auto rec = (struct RecordPacket *) SDL_malloc(sizeof(struct RecordPacket));
        if (!rec) {
            return nullptr;
        }

        // av_packet_ref() does not initialize all fields in old FFmpeg versions
        av_init_packet(&rec->packet);

        if (av_packet_ref(&rec->packet, packet)) {
            SDL_free(rec);
            return nullptr;
        }
        return rec;
    }

    const AVOutputFormat *Recorder::FindMuxer(const char *name) {
#ifdef IROBOT_LAVF_HAS_NEW_MUXER_ITERATOR_API
        void *opaque = nullptr;
#endif
        const AVOutputFormat *oformat = nullptr;
        do {
#ifdef IROBOT_LAVF_HAS_NEW_MUXER_ITERATOR_API
            oformat = av_muxer_iterate(&opaque);
#else
            oformat = av_oformat_next(oformat);
#endif
            // until null or with name "mp4"
        } while (oformat && strcmp(oformat->name, name));
        return oformat;
    }

    bool Recorder::Open(const AVCodec *input_codec) {

        const char *format_name = RecorderGetFormatName(this->format);
        assert(format_name);
        const AVOutputFormat *format = FindMuxer(format_name);
        if (!format) {
            LOGE("Could not find muxer");
            return false;
        }

        this->ctx = avformat_alloc_context();
        if (!this->ctx) {
            LOGE("Could not allocate output context");
            return false;
        }

        // contrary to the deprecated API (av_oformat_next()), av_muxer_iterate()
        // returns (on purpose) a pointer-to-const, but AVFormatContext.oformat
        // still expects a pointer-to-non-const (it has not be updated accordingly)
        // <https://github.com/FFmpeg/FFmpeg/commit/0694d8702421e7aff1340038559c438b61bb30dd>
        this->ctx->oformat = (AVOutputFormat *) format;

        av_dict_set(&this->ctx->metadata, "comment",
                    "Recorded by irobot "
                    IROBOT_SERVER_VERSION, 0);

        AVStream *ostream = avformat_new_stream(this->ctx, input_codec);
        if (!ostream) {
            avformat_free_context(this->ctx);
            return false;
        }


        ostream->codecpar->codec_type = AVMEDIA_TYPE_VIDEO;
        ostream->codecpar->codec_id = input_codec->id;
        ostream->codecpar->format = AV_PIX_FMT_YUV420P;
        ostream->codecpar->width = this->declared_frame_size.width;
        ostream->codecpar->height = this->declared_frame_size.height;


        int ret = avio_open(&this->ctx->pb, this->filename,
                            AVIO_FLAG_WRITE);
        if (ret < 0) {
            LOGE("Failed to open output file: %s", this->filename);
            // ostream will be cleaned up during context cleaning
            avformat_free_context(this->ctx);
            return false;
        }

        LOGI("Recording started to %s file: %s", format_name, this->filename);

        return true;
    }

    void Recorder::Close() {

        if (this->header_written) {
            int ret = av_write_trailer(this->ctx);
            if (ret < 0) {
                LOGE("Failed to write trailer to %s", this->filename);
                this->failed = true;
            }
        } else {
            // the recorded file is empty
            this->failed = true;
        }
        avio_close(this->ctx->pb);
        avformat_free_context(this->ctx);

        if (this->failed) {
            LOGE("Recording failed to %s", this->filename);
        } else {
            const char *format_name = RecorderGetFormatName(this->format);
            LOGI("Recording complete to %s file: %s", format_name, this->filename);
        }
    }

    bool Recorder::WriteHeader(const AVPacket *packet) {

        AVStream *ostream = this->ctx->streams[0];

        auto *extradata = static_cast<uint8_t *>(av_malloc(packet->size * sizeof(uint8_t)));
        if (!extradata) {
            LOGC("Could not allocate extradata");
            return false;
        }

        // copy the first packet to the extra data
        memcpy(extradata, packet->data, packet->size);

        ostream->codecpar->extradata = extradata;
        ostream->codecpar->extradata_size = packet->size;


        int ret = avformat_write_header(this->ctx, nullptr);
        if (ret < 0) {
            LOGE("Failed to write header to %s", this->filename);
            return false;
        }

        return true;
    }

    void Recorder::RescalePacket(AVPacket *packet) {

        AVStream *ostream = this->ctx->streams[0];
        av_packet_rescale_ts(packet, IROBOT_TIME_BASE, ostream->time_base);
    }

    bool Recorder::Write(AVPacket *packet) {

        if (!this->header_written) {
            if (packet->pts != AV_NOPTS_VALUE) {
                LOGE("The first packet is not a config packet");
                return false;
            }
            bool ok = this->WriteHeader(packet);
            if (!ok) {
                return false;
            }
            this->header_written = true;
            return true;
        }

        if (packet->pts == AV_NOPTS_VALUE) {
            // ignore config packets
            return true;
        }

        this->RescalePacket(packet);
        return av_write_frame(this->ctx, packet) >= 0;
    }

    int Recorder::RunRecorder(void *data) {
        auto *recorder = static_cast<struct Recorder *>(data);

        for (;;) {
            util::mutex_lock(recorder->mutex);

            while (!recorder->stopped && queue_is_empty(&recorder->queue)) {
                util::cond_wait(recorder->thread_cond, recorder->mutex);
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

        this->thread = SDL_CreateThread(RunRecorder, "recorder", this);
        if (!this->thread) {
            LOGC("Could not start recorder thread");
            return false;
        }

        return true;
    }


    bool Recorder::Push(const AVPacket *packet) {

        util::mutex_lock(this->mutex);
        assert(!this->stopped);

        if (this->failed) {
            // reject any new packet (this will stop the stream)
            return false;
        }

        struct RecordPacket *rec = RecordPacketNew(packet);
        if (!rec) {
            LOGC("Could not allocate record packet");
            return false;
        }

        queue_push(&this->queue, next, rec);
        util::cond_signal(this->thread_cond);

        util::mutex_unlock(this->mutex);
        return true;
    }

}