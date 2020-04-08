//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_RECORDER_HPP
#define ANDROID_IROBOT_RECORDER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <libavformat/avformat.h>
#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "core/common.hpp"

#include "util/queue.hpp"

namespace irobot::video {
    enum RecordFormat {
        RECORDER_FORMAT_AUTO,
        RECORDER_FORMAT_MP4,
        RECORDER_FORMAT_MKV,
    };

    struct RecordPacket {
        AVPacket packet;
        struct RecordPacket *next;
    };

    struct RecordQueue QUEUE(struct RecordPacket);

    class Recorder {
    public:

        char *filename;
        enum RecordFormat format;
        AVFormatContext *ctx;
        struct Size declared_frame_size;
        bool header_written;

        SDL_Thread *thread;
        SDL_mutex *mutex;
        SDL_cond *queue_cond;
        bool stopped; // set on recorder_stop() by the stream reader
        bool failed; // set on packet write failure
        struct RecordQueue queue;

        // we can write a packet only once we received the next one so that we can
        // set its duration (next_pts - current_pts)
        // "previous" is only accessed from the recorder thread, so it does not
        // need to be protected by the mutex
        struct RecordPacket *previous;

        bool Init(const char *filename,
                  enum RecordFormat format, struct Size declared_frame_size);

        void Destroy();

        bool Open(const AVCodec *input_codec);

        void Close();

        bool Start();

        void Stop();

        void Join();

        bool Push(const AVPacket *packet);

        bool Write(AVPacket *packet);

        static inline const AVOutputFormat *FindMuxer(const char *name) {
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

        static inline struct RecordPacket *RecordPacketNew(const AVPacket *packet) {
            auto rec = (struct RecordPacket *) SDL_malloc(sizeof(struct RecordPacket));
            if (!rec) {
                return nullptr;
            }

            // av_packet_ref() does not initialize all fields in old FFmpeg versions
            // See <https://github.com/Genymobile/scrcpy/issues/707>
            av_init_packet(&rec->packet);

            if (av_packet_ref(&rec->packet, packet)) {
                SDL_free(rec);
                return nullptr;
            }
            return rec;
        }

        static inline void RecordPacketDelete(struct RecordPacket *rec) {
            av_packet_unref(&rec->packet);
            SDL_free(rec);
        }

        static inline void RecorderQueueClear(struct RecordQueue *queue) {
            while (!queue_is_empty(queue)) {
                struct RecordPacket *rec;
                queue_take(queue, next, &rec);
                RecordPacketDelete(rec);
            }
        }

        static const char *RecorderGetFormatName(enum RecordFormat format) {
            switch (format) {
                case RECORDER_FORMAT_MP4:
                    return "mp4";
                case RECORDER_FORMAT_MKV:
                    return "matroska";
                default:
                    return nullptr;
            }
        }

        static int RunRecorder(void *data);

    private:

        bool WriteHeader(const AVPacket *packet);

        void RescalePacket(AVPacket *packet);

    };
}

#endif //ANDROID_IROBOT_RECORDER_HPP
