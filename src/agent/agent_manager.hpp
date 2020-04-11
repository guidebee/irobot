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

#include "ui/events.hpp"
#include "core/controller.hpp"
#include "video/video_buffer.hpp"

#define EVENT_FILE_NAME "events.json"

namespace irobot::agent {

    class AgentManager {

    public:
        Controller *controller = nullptr;
        video::VideoBuffer *video_buffer = nullptr;
        SDL_RWops *fp_events = nullptr;

        ui::EventResult HandleEvent(SDL_Event *event, bool has_screen);

        void ProcessKey(const SDL_KeyboardEvent *event);

        bool PushDeviceControlMessage(const message::ControlMessage *msg);
    };


}
#endif //ANDROID_IROBOT_NULL_INPUT_MANAGER_HPP
