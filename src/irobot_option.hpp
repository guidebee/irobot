//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_SCRCPY_HPP
#define ANDROID_IROBOT_SCRCPY_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <libavformat/avformat.h>

#if defined (__cplusplus)
}
#endif

#include <cstdint>

#include "config.hpp"
#include "ui/input_manager.hpp"
#include "video/recorder.hpp"

struct IRobotOptions {
    const char *serial;
    const char *crop;
    const char *record_filename;
    const char *window_title;
    const char *push_target;
    enum recorder_format record_format;
    uint16_t port;
    uint16_t max_size;
    uint32_t bit_rate;
    uint16_t max_fps;
    int16_t window_x;
    int16_t window_y;
    uint16_t window_width;
    uint16_t window_height;
    bool show_touches;
    bool fullscreen;
    bool always_on_top;
    bool control;
    bool display;
    bool turn_screen_off;
    bool render_expired_frames;
    bool prefer_text;
    bool window_borderless;
    uint16_t screen_width;
    uint16_t screen_height;

    IRobotOptions();

    bool init();
};



#endif //ANDROID_IROBOT_SCRCPY_HPP
