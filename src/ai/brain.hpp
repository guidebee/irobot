//
// Created by James Shen on 8/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_BRAIN_HPP
#define ANDROID_IROBOT_BRAIN_HPP

#include "video/video_buffer.hpp"

namespace irobot::ai {
    void ProcessFrame(video::VideoBuffer video_buffer);
}

#endif //ANDROID_IROBOT_BRAIN_HPP
