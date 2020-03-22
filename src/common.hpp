//
// Created by James Shen on 22/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_COMMON_HPP
#define ANDROID_IROBOT_COMMON_HPP
#if defined (__cplusplus)
extern "C" {
#endif
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
#include <libavutil/imgutils.h>
#include <cstdio>

#if defined (__cplusplus)
}
#endif

#define IMAGE_ALIGN 1

void save_frame(AVFrame *pFrame,
                int width, int height, int iFrame);

int decode_frame(AVCodecContext *pCodecContext,
                 AVFrame *pFrame, const AVPacket *pPacket);
#endif //ANDROID_IROBOT_COMMON_HPP
