//
// Created by James Shen on 8/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_BRAIN_HPP
#define ANDROID_IROBOT_BRAIN_HPP

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/highgui.hpp>
#include <opencv2/imgproc/imgproc.hpp>

#include "video/video_buffer.hpp"

namespace irobot::ai {
    void SaveFrame(video::VideoBuffer video_buffer);

    cv::Mat ConvertToMat(video::VideoBuffer video_buffer, int max_size, bool color);

}

#endif //ANDROID_IROBOT_BRAIN_HPP
