//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_INPUT_MANAGER_HPP
#define ANDROID_IROBOT_INPUT_MANAGER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <stdbool.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "common.hpp"
#include "controller.hpp"
#include "video/fps_counter.hpp"
#include "video/video_buffer.hpp"
#include "ui/screen.hpp"

struct input_manager {
    struct controller *controller;
    struct video_buffer *video_buffer;
    struct screen *screen;
    bool prefer_text;
};

void
input_manager_process_text_input(struct input_manager *im,
                                 const SDL_TextInputEvent *event);

void
input_manager_process_key(struct input_manager *im,
                          const SDL_KeyboardEvent *event,
                          bool control);

void
input_manager_process_mouse_motion(struct input_manager *im,
                                   const SDL_MouseMotionEvent *event);

void
input_manager_process_touch(struct input_manager *im,
                            const SDL_TouchFingerEvent *event);

void
input_manager_process_mouse_button(struct input_manager *im,
                                   const SDL_MouseButtonEvent *event,
                                   bool control);

void
input_manager_process_mouse_wheel(struct input_manager *im,
                                  const SDL_MouseWheelEvent *event);


#endif //ANDROID_IROBOT_INPUT_MANAGER_HPP
