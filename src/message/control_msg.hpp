//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CONTROL_MSG_HPP
#define ANDROID_IROBOT_CONTROL_MSG_HPP

#include <cstddef>
#include <cstdint>

#include "config.hpp"
#include "android/input.hpp"
#include "android/keycodes.hpp"
#include "common.hpp"

#define CONTROL_MSG_TEXT_MAX_LENGTH 300
#define CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH 4093
#define CONTROL_MSG_SERIALIZED_MAX_SIZE \
    (3 + CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH)

#define POINTER_ID_MOUSE UINT64_C(-1);

enum control_msg_type {
    CONTROL_MSG_TYPE_INJECT_KEYCODE,
    CONTROL_MSG_TYPE_INJECT_TEXT,
    CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
    CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT,
    CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON,
    CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL,
    CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL,
    CONTROL_MSG_TYPE_GET_CLIPBOARD,
    CONTROL_MSG_TYPE_SET_CLIPBOARD,
    CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE,
    CONTROL_MSG_TYPE_ROTATE_DEVICE,
    CONTROL_MSG_TYPE_START_RECORDING,
    CONTROL_MSG_TYPE_END_RECORDING,
};

enum screen_power_mode {
    // see <https://android.googlesource.com/platform/frameworks/base.git/+/pie-release-2/core/java/android/view/SurfaceControl.java#305>

    SCREEN_POWER_MODE_OFF = 0,
    SCREEN_POWER_MODE_NORMAL = 2,
};

struct control_msg {
    enum control_msg_type type;
    union {
        struct {
            enum android_keyevent_action action;
            enum android_keycode keycode;
            enum android_metastate metastate;
        } inject_keycode;
        struct {
            char *text; // owned, to be freed by SDL_free()
        } inject_text;
        struct {
            enum android_motionevent_action action;
            enum android_motionevent_buttons buttons;
            uint64_t pointer_id;
            struct position position;
            float pressure;
        } inject_touch_event;
        struct {
            struct position position;
            int32_t hscroll;
            int32_t vscroll;
        } inject_scroll_event;
        struct {
            char *text; // owned, to be freed by SDL_free()
        } set_clipboard;
        struct {
            enum screen_power_mode mode;
        } set_screen_power_mode;
    };
};

// buf size must be at least CONTROL_MSG_SERIALIZED_MAX_SIZE
// return the number of bytes written
size_t
control_msg_serialize(const struct control_msg *msg, unsigned char *buf);

void
control_msg_destroy(struct control_msg *msg);

char *
control_msg_json_serialize(const struct control_msg *msg);

size_t
control_msg_json_deserialize(struct control_msg *msg, const unsigned char *buf, size_t len);

#endif //ANDROID_IROBOT_CONTROL_MSG_HPP
