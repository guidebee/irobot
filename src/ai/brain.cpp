//
// Created by James Shen on 8/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//


#include "brain.hpp"


#include "video/decoder.hpp"
#include "util/lock.hpp"
#include "core/common.hpp"


namespace irobot::ai {


    void ProcessFrame(video::VideoBuffer video_buffer) {

        video::VideoBuffer *vb = &video_buffer;
        util::mutex_lock(vb->mutex);
        AVFrame *frame = vb->rgb_frame;
        struct Size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
        LOGI("receive new cv frame %d,%d\n", new_frame_size.width, new_frame_size.height);
        video::Decoder::SaveFrame(frame, new_frame_size.width, new_frame_size.height, 0);
        util::mutex_unlock(vb->mutex);
    }
}