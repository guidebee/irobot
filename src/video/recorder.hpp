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
#include "common.hpp"

#include "util/queue.hpp"

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
    struct size declared_frame_size;
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

    bool init(const char *filename,
              enum RecordFormat format, struct size declared_frame_size);

    void destroy();

    bool open(const AVCodec *input_codec);

    void close();

    bool start();

    void stop();

    void join();

    bool push(const AVPacket *packet);

    bool write(AVPacket *packet);

private:

    bool write_header(const AVPacket *packet);

    void rescale_packet(AVPacket *packet);

};


#endif //ANDROID_IROBOT_RECORDER_HPP
