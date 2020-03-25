//
// Created by James Shen on 22/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//
#include "utils.hpp"

int decode_frame(AVCodecContext *pCodecContext,
                 AVFrame *pFrame,
                 const AVPacket *pPacket) {
    int frameFinished = 0;
    int ret = avcodec_receive_frame(pCodecContext, pFrame);
    if (ret == 0)
        frameFinished = 1;
    if (ret == 0 || ret == AVERROR(EAGAIN))
        avcodec_send_packet(pCodecContext, pPacket);
    return frameFinished;
}

void save_frame(AVFrame *pFrame,
                int width, int height, int iFrame) {
    FILE *pFile;
    char szFilename[32];
    int y;
    // Open file
    sprintf(szFilename, "frame%d.ppm", iFrame);
    pFile = fopen(szFilename, "wb");
    if (pFile == nullptr)
        return;
    // Write header
    fprintf(pFile, "P6\n%d %d\n255\n", width, height);
    // Write pixel data
    for (y = 0; y < height; y++)
        fwrite(pFrame->data[0] + y * pFrame->linesize[0], 1, width * 3, pFile);
    // Close file
    fclose(pFile);
}