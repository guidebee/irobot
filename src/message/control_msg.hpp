//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CONTROL_MSG_HPP
#define ANDROID_IROBOT_CONTROL_MSG_HPP

#define CONTROL_MSG_TEXT_MAX_LENGTH 300
#define CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH 4093
#define CONTROL_MSG_SERIALIZED_MAX_SIZE \
    (3 + CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH)

#define POINTER_ID_MOUSE UINT64_C(-1)

#include <cstddef>
#include <cstdint>
#include <string>

#include "util/cbuf.hpp"
#include "core/common.hpp"
#include "android/input.hpp"
#include "android/keycodes.hpp"

namespace irobot::message {


    using namespace irobot::android;

    enum ControlMessageType {
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
        CONTROL_MSG_TYPE_UNKNOWN,
    };

    enum ScreenPowerMode {
        // see <https://android.googlesource.com/platform/frameworks/base.git/+/pie-release-2/core/java/android/view/SurfaceControl.java#305>

        SCREEN_POWER_MODE_OFF = 0,
        SCREEN_POWER_MODE_NORMAL = 2,
    };

    struct ControlMessage {
        enum ControlMessageType type;
        union {
            struct {
                enum AndroidKeyEventAction action;
                enum AndroidKeycode keycode;
                enum AndroidMetaState metastate;
            } inject_keycode;
            struct {
                char *text; // owned, to be freed by SDL_free()
            } inject_text;
            struct {
                enum AndroidMotionEventAction action;
                enum AndroidMotionEventButtons buttons;
                uint64_t pointer_id;
                struct Position position;
                float pressure;
            } inject_touch_event;
            struct {
                struct Position position;
                int32_t hscroll;
                int32_t vscroll;
            } inject_scroll_event;
            struct {
                char *text; // owned, to be freed by SDL_free()
            } set_clipboard;
            struct {
                enum ScreenPowerMode mode;
            } set_screen_power_mode;
        };

        // buf size must be at least CONTROL_MSG_SERIALIZED_MAX_SIZE
        // return the number of bytes written
        size_t Serialize(unsigned char *buf);

        void Destroy();

        std::string JsonSerialize();

        size_t JsonDeserialize(const unsigned char *buf, size_t len);

        static void WritePosition(uint8_t *buf, const struct Position *position);

        // write length (2 bytes) + string (non nul-terminated)
        static size_t WriteString(const char *utf8, size_t max_len, unsigned char *buf);

        static uint16_t ToFixedPoint16(float f);
    };

    struct ControlMessageQueue CBUF(ControlMessage, 64);
}
#endif //ANDROID_IROBOT_CONTROL_MSG_HPP
