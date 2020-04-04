//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CORE_HPP
#define ANDROID_IROBOT_CORE_HPP

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
#include "platform/command.hpp"
#include "ui/input_manager.hpp"
#include "video/recorder.hpp"

namespace irobot {


    class IRobotCore {

    public:
        const char *serial;
        const char *crop;
        const char *record_filename;
        const char *window_title;
        const char *push_target;
        enum video::RecordFormat record_format;
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

        IRobotCore();

        bool Init();

        bool ParseArgs(int argc, char **argv);

        static ProcessType SetShowTouchesEnabled(const char *serial, bool enabled);

        static void WaitShowTouches(ProcessType process);

        static SDL_LogPriority SDLPriorityFromAVLevel(int level);

        static void AVLogCallback(void *avcl, int level,
                                  const char *fmt, va_list vl);

        static bool ParseIntegerArg(const char *s, long *out,
                                    bool accept_suffix, long min,
                                    long max, const char *name);

        static bool ParseBitRate(const char *s, uint32_t *bit_rate);

        static bool ParseMaxSize(const char *s, uint16_t *max_size);

        static bool ParseMaxFps(const char *s, uint16_t *max_fps);

        static bool ParseWindowPosition(const char *s, int16_t *position);

        static bool ParseWindowDimension(const char *s, uint16_t *dimension);

        static bool ParsePort(const char *s, uint16_t *port);

        static bool ParseRecordFormat(const char *opt_arg,
                                      enum video::RecordFormat *format);

        static enum video::RecordFormat GuessRecordFormat(const char *filename);

        static void PrintUsage(const char *arg0);

        static void PrintVersion();

        static int iRobotMain(int argc, char **argv);
    };

}

#endif //ANDROID_IROBOT_CORE_HPP
