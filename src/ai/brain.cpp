//
// Created by James Shen on 8/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//


#include "brain.hpp"

#include "video/decoder.hpp"
#include "util/lock.hpp"
#include "core/common.hpp"


namespace irobot::ai {


    void SaveFrame(video::VideoBuffer video_buffer) {
        video::VideoBuffer *vb = &video_buffer;
        util::mutex_lock(vb->mutex);
        AVFrame *frame = vb->rgb_frame;
        struct Size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
        LOGI("Screen capture in opencv BGR format %d,%d\n", new_frame_size.width, new_frame_size.height);
        video::Decoder::SaveFrame(frame, vb->frame_number);
        util::mutex_unlock(vb->mutex);
    }

    cv::Mat ConvertToMat(video::VideoBuffer video_buffer, int max_size, bool color) {
        util::mutex_lock(video_buffer.mutex);
        AVFrame *pFrameRGB = video_buffer.rgb_frame;
        int width = pFrameRGB->width;
        int height = pFrameRGB->height;
        cv::Mat image(height, width, CV_8UC3, pFrameRGB->data[0], pFrameRGB->linesize[0]);
        cv::Mat greyMat;
        cv::Mat outImg;
        int maxSize = MAX(image.size().width, image.size().height);
        float scale = (float) max_size / (float) maxSize;
        cv::resize(image, outImg, cv::Size(), scale, scale);
        if(!color){
            cv::cvtColor(outImg, greyMat, cv::COLOR_BGR2GRAY);
            outImg = greyMat;
        }
        util::mutex_unlock(video_buffer.mutex);
        return outImg;
    }
}