//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "scrcpy.hpp"

#include <cstring>

#include "command.hpp"
#include "common.hpp"
#include "controller.hpp"
#include "server.hpp"

#include "android/device.hpp"
#include "android/file_handler.hpp"
#include "ui/screen.hpp"
#include "ui/irobot_ui.hpp"
#include "video/decoder.hpp"
#include "video/fps_counter.hpp"
#include "video/recorder.hpp"
#include "video/stream.hpp"
#include "video/video_buffer.hpp"
#include "util/log.hpp"
#include "util/net.hpp"

static Server server{};
static struct fps_counter fps_counter;
struct video_buffer video_buffer;
static struct stream stream;

static struct recorder recorder;
struct controller controller;
struct file_handler file_handler;

static struct decoder decoder;
extern struct input_manager input_manager;
extern struct screen screen;

static process_t
set_show_touches_enabled(const char *serial, bool enabled) {
    const char *value = enabled ? "1" : "0";
    const char *const adb_cmd[] = {
            "shell", "settings", "put", "system", "show_touches", value
    };
    return adb_execute(serial, adb_cmd, ARRAY_LEN(adb_cmd));
}

static void
wait_show_touches(process_t process) {
    // reap the process, ignore the result
    process_check_success(process, "show_touches");
}

static SDL_LogPriority
sdl_priority_from_av_level(int level) {
    switch (level) {
        case AV_LOG_PANIC:
        case AV_LOG_FATAL:
            return SDL_LOG_PRIORITY_CRITICAL;
        case AV_LOG_ERROR:
            return SDL_LOG_PRIORITY_ERROR;
        case AV_LOG_WARNING:
            return SDL_LOG_PRIORITY_WARN;
        case AV_LOG_INFO:
            return SDL_LOG_PRIORITY_INFO;
        default:
            return static_cast<SDL_LogPriority>(0);
    }
}

static void
av_log_callback(void *avcl, int level, const char *fmt, va_list vl) {
    (void) avcl;
    SDL_LogPriority priority = sdl_priority_from_av_level(level);
    if (priority == 0) {
        return;
    }
    char *local_fmt = static_cast<char *>(SDL_malloc(strlen(fmt) + 10));
    if (!local_fmt) {
        LOGC("Could not allocate string");
        return;
    }
    // strcpy is safe here, the destination is large enough
    strcpy(local_fmt, "[FFmpeg] ");
    strcpy(local_fmt + 9, fmt);
    SDL_LogMessageV(SDL_LOG_CATEGORY_VIDEO, priority, local_fmt, vl);
    SDL_free(local_fmt);
}

bool
scrcpy(const struct scrcpy_options *options) {
    bool record = options->record_filename != nullptr;
    struct ServerParameters params = {
            .crop = options->crop,
            .local_port = options->port,
            .max_size = options->max_size,
            .bit_rate = options->bit_rate,
            .max_fps = options->max_fps,
            .control = options->control,
    };
    if (!server.start(options->serial, &params)) {
        return false;
    }

    process_t proc_show_touches = PROCESS_NONE;
    bool show_touches_waited = false;
    if (options->show_touches) {
        LOGI("Enable show_touches");
        proc_show_touches = set_show_touches_enabled(options->serial, true);
        show_touches_waited = false;
    }

    bool fps_counter_initialized = false;
    bool video_buffer_initialized = false;
    bool file_handler_initialized = false;
    bool recorder_initialized = false;
    bool controller_initialized = false;
    bool controller_started = false;

    bool cannot_cont = false;
    if (!sdl_init_and_configure(options->display)) {
        cannot_cont = true;
    }

    if (!cannot_cont & !server.connect_to()) {
        cannot_cont = true;
    }

    char device_name[DEVICE_NAME_FIELD_LENGTH];
    struct size frame_size{};

    // screenrecord does not send frames when the screen content does not
    // change therefore, we transmit the screen size before the video stream,
    // to be able to init the window immediately
    if (!cannot_cont & !device_read_info(server.video_socket, device_name, &frame_size)) {
        cannot_cont = true;
    }

    struct decoder *dec = nullptr;
    if (!cannot_cont & options->display) {
        if (!fps_counter_init(&fps_counter)) {
            cannot_cont = true;
        }
        fps_counter_initialized = true;

        if (!cannot_cont & !video_buffer_init(&video_buffer, &fps_counter,
                                              options->render_expired_frames)) {
            cannot_cont = true;
        }
        video_buffer_initialized = true;

        if (!cannot_cont & options->control) {
            if (!file_handler_init(&file_handler, server.serial,
                                   options->push_target)) {
                cannot_cont = true;
            }
            file_handler_initialized = true;
        }

        decoder_init(&decoder, &video_buffer);
        dec = &decoder;
    }

    struct recorder *rec = nullptr;
    if (!cannot_cont & record) {
        if (!recorder_init(&recorder,
                           options->record_filename,
                           options->record_format,
                           frame_size)) {
            cannot_cont = true;
        }
        rec = &recorder;
        recorder_initialized = true;
    }

    av_log_set_callback(av_log_callback);

    stream_init(&stream, server.video_socket, dec, rec);


    // now we consumed the header values, the socket receives the video stream
    // start the stream
    if (!cannot_cont & !stream_start(&stream)) {
        cannot_cont = true;
    }


    if (!cannot_cont & options->display) {
        if (options->control) {
            if (!controller_init(&controller, server.control_socket)) {
                cannot_cont = true;
            }
            controller_initialized = true;

            if (!controller_start(&controller)) {
                cannot_cont = true;
            }
            controller_started = true;
        }

        const char *window_title =
                options->window_title ? options->window_title : device_name;

        if (!cannot_cont & !screen_init_rendering(&screen, window_title, frame_size,
                                                  options->always_on_top, options->window_x,
                                                  options->window_y, options->window_width,
                                                  options->window_height, options->screen_width,
                                                  options->screen_height,
                                                  options->window_borderless)) {
            cannot_cont = true;
        }

        if (!cannot_cont & options->turn_screen_off) {
            struct control_msg msg{};
            msg.type = CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE;
            msg.set_screen_power_mode.mode = SCREEN_POWER_MODE_OFF;

            if (!controller_push_msg(&controller, &msg)) {
                LOGW("Could not request 'set screen power mode'");
            }
        }

        if (options->fullscreen) {
            screen_switch_fullscreen(&screen);
        }
    }

    if (options->show_touches) {
        wait_show_touches(proc_show_touches);
        show_touches_waited = true;
    }

    input_manager.prefer_text = options->prefer_text;

    bool ret = event_loop(options->display, options->control);
    LOGD("quit...");

    screen_destroy(&screen);


    // stop stream and controller so that they don't continue once their socket
    // is shutdown
    stream_stop(&stream);

    if (controller_started) {
        controller_stop(&controller);
    }
    if (file_handler_initialized) {
        file_handler_stop(&file_handler);
    }
    if (fps_counter_initialized) {
        fps_counter_interrupt(&fps_counter);
    }

    // shutdown the sockets and kill the server
    server.stop();

    // now that the sockets are shutdown, the stream and controller are
    // interrupted, we can join them
    stream_join(&stream);


    if (controller_started) {
        controller_join(&controller);
    }
    if (controller_initialized) {
        controller_destroy(&controller);
    }

    if (recorder_initialized) {
        recorder_destroy(&recorder);
    }

    if (file_handler_initialized) {
        file_handler_join(&file_handler);
        file_handler_destroy(&file_handler);
    }

    if (video_buffer_initialized) {
        video_buffer_destroy(&video_buffer);
    }

    if (fps_counter_initialized) {
        fps_counter_join(&fps_counter);
        fps_counter_destroy(&fps_counter);
    }

    if (options->show_touches) {
        if (!show_touches_waited) {
            // wait the process which enabled "show touches"
            wait_show_touches(proc_show_touches);
        }
        LOGI("Disable show_touches");
        proc_show_touches = set_show_touches_enabled(options->serial, false);
        wait_show_touches(proc_show_touches);
    }

    server.destroy();

    return ret;
}
