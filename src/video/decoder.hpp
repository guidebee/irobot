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

class VideoBuffer;

class Decoder {
public:
    VideoBuffer *video_buffer;
    AVCodecContext *codec_ctx;



    void init(VideoBuffer *vb);

    bool open(const AVCodec *codec);

    void close();

    bool push(const AVPacket *packet);

    void interrupt();

private:
    void push_frame();
};


#endif //ANDROID_IROBOT_DECODER_HPP
