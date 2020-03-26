//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_EVENT_CONVERTER_HPP
#define ANDROID_IROBOT_EVENT_CONVERTER_HPP

#include <SDL2/SDL_events.h>

#include "config.hpp"
#include "message/control_msg.hpp"

bool
convert_keycode_action(SDL_EventType from, enum android_keyevent_action *to);

enum android_metastate
convert_meta_state(SDL_Keymod mod);

bool
convert_keycode(SDL_Keycode from, enum android_keycode *to, uint16_t mod,
                bool prefer_text);

enum android_motionevent_buttons
convert_mouse_buttons(uint32_t state);

bool
convert_mouse_action(SDL_EventType from, enum android_motionevent_action *to);

bool
convert_touch_action(SDL_EventType from, enum android_motionevent_action *to);

#endif //ANDROID_IROBOT_EVENT_CONVERTER_HPP
