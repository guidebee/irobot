//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "event_converter.hpp"
#include "config.hpp"

#define MAP(FROM, TO) case FROM: *to = TO; return true
#define FAIL default: return false

bool
convert_keycode_action(SDL_EventType from, enum android_keyevent_action *to) {
    switch (from) {
        MAP(SDL_KEYDOWN, AKEY_EVENT_ACTION_DOWN);
        MAP(SDL_KEYUP,   AKEY_EVENT_ACTION_UP);
        FAIL;
    }
}

static enum android_metastate
autocomplete_metastate(enum android_metastate metastate) {
    // fill dependant flags
    if (metastate & (AMETA_SHIFT_LEFT_ON | AMETA_SHIFT_RIGHT_ON)) {
        metastate = static_cast<android_metastate>(metastate | AMETA_SHIFT_ON);
    }
    if (metastate & (AMETA_CTRL_LEFT_ON | AMETA_CTRL_RIGHT_ON)) {
        metastate = static_cast<android_metastate>(metastate | AMETA_CTRL_ON);

    }
    if (metastate & (AMETA_ALT_LEFT_ON | AMETA_ALT_RIGHT_ON)) {
        metastate = static_cast<android_metastate>(metastate | AMETA_ALT_ON);

    }
    if (metastate & (AMETA_META_LEFT_ON | AMETA_META_RIGHT_ON)) {
        metastate = static_cast<android_metastate>(metastate | AMETA_META_ON);

    }

    return metastate;
}

