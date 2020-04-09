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

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "core/common.hpp"
#include "core/actor.hpp"
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

    class Recorder : public Actor {
    public:

        char *filename;
        enum RecordFormat format;
        AVFormatContext *ctx;
        struct Size declared_frame_size;
        bool header_written;

        bool failed; // set on packet write failure
        struct RecordQueue queue;

        // we can write a packet only once we received the next one so that we can
        // set its duration (next_pts - current_pts)
        // "previous" is only accessed from the recorder thread, so it does not
        // need to be protected by the mutex
        struct RecordPacket *previous;

        bool Init(const char *filename,
                  enum RecordFormat format, struct Size declared_frame_size);

        void Destroy() override;

        bool Open(const AVCodec *input_codec);

        void Close();

        bool Start() override;

        bool Push(const AVPacket *packet);

        bool Write(AVPacket *packet);

        static const AVOutputFormat *FindMuxer(const char *name);

        static RecordPacket *RecordPacketNew(const AVPacket *packet);

        static void RecordPacketDelete(struct RecordPacket *rec);

        static void RecorderQueueClear(struct RecordQueue *queue);

        static const char *RecorderGetFormatName(enum RecordFormat format);

        static int RunRecorder(void *data);

    private:

        bool WriteHeader(const AVPacket *packet);

        void RescalePacket(AVPacket *packet);

    };
}

#endif //ANDROID_IROBOT_RECORDER_HPP
