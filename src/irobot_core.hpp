//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_SCRCPY_HPP
#define ANDROID_IROBOT_SCRCPY_HPP

#define SDL_MAIN_HANDLED // avoid link error on Linux Windows Subsystem

#if defined (__cplusplus)
extern "C" {
#endif
#include <getopt.h>
#include <unistd.h>
#include <libavformat/avformat.h>

#if defined (__cplusplus)
}
#endif

#include <cstdint>

#include "config.hpp"
#include "command.hpp"
#include "ui/input_manager.hpp"
#include "video/recorder.hpp"

class IRobotCore {

public:
    const char *serial;
    const char *crop;
    const char *record_filename;
    const char *window_title;
    const char *push_target;
    enum RecordFormat record_format;
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
    bool help;
    bool version;


    bool init();


    static ProcessType set_show_touches_enabled(const char *serial, bool enabled);

    static void wait_show_touches(ProcessType process);

    static SDL_LogPriority sdl_priority_from_av_level(int level);

    static void av_log_callback(void *avcl, int level, const char *fmt, va_list vl);

    IRobotCore();

    bool parse_args(int argc, char *argv[]);

    static void irobot_print_usage(const char *arg0);

    static void print_version();

    static int irobot_main(int argc, char *argv[]);
};


#endif //ANDROID_IROBOT_SCRCPY_HPP
