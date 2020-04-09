//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_NULL_INPUT_MANAGER_HPP
#define ANDROID_IROBOT_NULL_INPUT_MANAGER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_events.h>
#if defined (__cplusplus)
}
#endif


#include "core/controller.hpp"
#include "video/video_buffer.hpp"

namespace irobot::ui {

    enum EventResult {
        EVENT_RESULT_CONTINUE,
        EVENT_RESULT_STOPPED_BY_USER,
        EVENT_RESULT_STOPPED_BY_EOS,
    };

    class NullInputManager {
    public:
        Controller *controller;
        video::VideoBuffer *video_buffer;

        enum EventResult HandleEvent(SDL_Event *event, bool has_screen);
    };

}
#endif //ANDROID_IROBOT_NULL_INPUT_MANAGER_HPP
