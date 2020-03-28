//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_DECODER_HPP
#define ANDROID_IROBOT_DECODER_HPP

#if defined (__cplusplus)
extern "C" {
#endif
#include <SDL2/SDL_events.h>
#include <libavformat/avformat.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"

struct video_buffer;

struct decoder {
    struct video_buffer *video_buffer;
    AVCodecContext *codec_ctx;
};

void
decoder_init(struct decoder *decoder, struct video_buffer *vb);

bool
decoder_open(struct decoder *decoder, const AVCodec *codec);

void
decoder_close(struct decoder *decoder);

bool
decoder_push(struct decoder *decoder, const AVPacket *packet);

void
decoder_interrupt(struct decoder *decoder);
#endif //ANDROID_IROBOT_DECODER_HPP
