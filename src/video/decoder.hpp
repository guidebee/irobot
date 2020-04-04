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

namespace irobot::video {

    class VideoBuffer;

    class Decoder {

    public:
        VideoBuffer *video_buffer;
        AVCodecContext *codec_ctx;

        void Init(VideoBuffer *vb);

        bool Open(const AVCodec *codec);

        void Close();

        bool Push(const AVPacket *packet);

        void Interrupt();

    private:
        void PushFrame();
    };
}

#endif //ANDROID_IROBOT_DECODER_HPP
