//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_EVENT_CONVERTER_HPP
#define ANDROID_IROBOT_EVENT_CONVERTER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_events.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"

#include "message/control_msg.hpp"


namespace irobot::ui {

    using namespace irobot::android;

    bool ConvertKeycodeAction(SDL_EventType from,
                              enum AndroidKeyEventAction *to);

    enum AndroidMetaState ConvertMetaState(SDL_Keymod mod);

    bool ConvertKeycode(SDL_Keycode from, enum AndroidKeycode *to,
                        uint16_t mod,
                        bool prefer_text);

    enum AndroidMotionEventButtons ConvertMouseButtons(uint32_t state);

    bool ConvertMouseAction(SDL_EventType from,
                            enum AndroidMotionEventAction *to);

    bool ConvertTouchAction(SDL_EventType from,
                            enum AndroidMotionEventAction *to);

}
#endif //ANDROID_IROBOT_EVENT_CONVERTER_HPP
