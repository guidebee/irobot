//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_INPUT_MANAGER_HPP
#define ANDROID_IROBOT_INPUT_MANAGER_HPP

#include "config.hpp"
#include "common.hpp"
#include "controller.hpp"

#include "ui/screen.hpp"

#include "video/fps_counter.hpp"
#include "video/video_buffer.hpp"


class InputManager {
public:
    class Controller *controller;

    struct video_buffer *video_buffer;
    struct screen *screen;
    bool prefer_text;

    void process_text_input(
            const SDL_TextInputEvent *event);

    void process_key(
            const SDL_KeyboardEvent *event,
            bool control);

    void process_mouse_motion(
            const SDL_MouseMotionEvent *event);

    void process_touch(
            const SDL_TouchFingerEvent *event);

    void process_mouse_button(
            const SDL_MouseButtonEvent *event,
            bool control);

    void process_mouse_wheel(
            const SDL_MouseWheelEvent *event);
};


#endif //ANDROID_IROBOT_INPUT_MANAGER_HPP
