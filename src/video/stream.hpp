//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_STREAM_HPP
#define ANDROID_IROBOT_STREAM_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <unistd.h>
#include <libavformat/avformat.h>
#include <SDL2/SDL_events.h>
#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>
#include <SDL2/SDL_atomic.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif

#include <cassert>
#include <cstdint>

#include "config.hpp"

#include "util/net.hpp"
#include "video/decoder.hpp"

struct stream {
    socket_t socket;
    SDL_Thread *thread;
    struct Decoder *decoder;
    struct Recorder *recorder;
    AVCodecContext *codec_ctx;
    AVCodecParserContext *parser;
    // successive packets may need to be concatenated, until a non-config
    // packet is available
    bool has_pending;
    AVPacket pending;
};

void
stream_init(struct stream *stream, socket_t socket,
            struct Decoder *decoder, Recorder *recorder);

bool
stream_start(struct stream *stream);

void
stream_stop(struct stream *stream);

void
stream_join(struct stream *stream);

#endif //ANDROID_IROBOT_STREAM_HPP
