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

    static inline const AVOutputFormat *find_muxer(const char *name) {
#ifdef SCRCPY_LAVF_HAS_NEW_MUXER_ITERATOR_API
        void *opaque = nullptr;
#endif
        const AVOutputFormat *oformat = nullptr;
        do {
#ifdef SCRCPY_LAVF_HAS_NEW_MUXER_ITERATOR_API
            oformat = av_muxer_iterate(&opaque);
#else
            oformat = av_oformat_next(oformat);
#endif
            // until null or with name "mp4"
        } while (oformat && strcmp(oformat->name, name));
        return oformat;
    }

    static inline struct RecordPacket *record_packet_new(const AVPacket *packet) {
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

    static inline void record_packet_delete(struct RecordPacket *rec) {
        av_packet_unref(&rec->packet);
        SDL_free(rec);
    }

    static inline void recorder_queue_clear(struct RecordQueue *queue) {
        while (!queue_is_empty(queue)) {
            struct RecordPacket *rec;
            queue_take(queue, next, &rec);
            record_packet_delete(rec);
        }
    }

    static const char *recorder_get_format_name(enum RecordFormat format) {
        switch (format) {
            case RECORDER_FORMAT_MP4:
                return "mp4";
            case RECORDER_FORMAT_MKV:
                return "matroska";
            default:
                return nullptr;
        }
    }

    static int run_recorder(void *data);

private:

    bool write_header(const AVPacket *packet);

    void rescale_packet(AVPacket *packet);

};


#endif //ANDROID_IROBOT_RECORDER_HPP
