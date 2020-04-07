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
#include <libswscale/swscale.h>
#include <libavutil/imgutils.h>
#if defined (__cplusplus)
}
#endif

#include "config.hpp"

#define IMAGE_ALIGN 1

namespace irobot::video {

    class VideoBuffer;

    class Decoder {

    public:
        VideoBuffer *video_buffer;
        AVCodecContext *codec_ctx;
        AVCodecContext *codec_cv_ctx;
        SwsContext *sws_cv_ctx;


        void Init(VideoBuffer *vb);

        bool Open(const AVCodec *codec);

        void Close();

        bool Push(const AVPacket *packet);

        void Interrupt();


        static void SaveFrame(AVFrame *pFrameRGB,
                              int width, int height, int iFrame);

    private:
        void PushFrame();
    };
}

#endif //ANDROID_IROBOT_DECODER_HPP
