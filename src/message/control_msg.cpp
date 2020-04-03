//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "control_msg.hpp"

#include <cassert>
#include <cstring>

#include "util/buffer_util.hpp"
#include "util/log.hpp"
#include "util/str_util.hpp"

namespace irobot::message {

    size_t ControlMessage::Serialize(unsigned char *buf) {
        struct ControlMessage *msg = this;
        buf[0] = msg->type;
        switch (msg->type) {
            case CONTROL_MSG_TYPE_INJECT_KEYCODE:
                buf[1] = msg->inject_keycode.action;
                util::buffer_write32be(&buf[2], msg->inject_keycode.keycode);
                util::buffer_write32be(&buf[6], msg->inject_keycode.metastate);
                return 10;
            case CONTROL_MSG_TYPE_INJECT_TEXT: {
                size_t len = WriteString(msg->inject_text.text,
                                         CONTROL_MSG_TEXT_MAX_LENGTH, &buf[1]);
                return 1 + len;
            }
            case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: {
                buf[1] = msg->inject_touch_event.action;
                util::buffer_write64be(&buf[2], msg->inject_touch_event.pointer_id);
                WritePosition(&buf[10], &msg->inject_touch_event.position);
                uint16_t pressure =
                        ToFixedPoint16(msg->inject_touch_event.pressure);
                util::buffer_write16be(&buf[22], pressure);
                util::buffer_write32be(&buf[24], msg->inject_touch_event.buttons);
                return 28;
            }
            case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
                WritePosition(&buf[1], &msg->inject_scroll_event.position);
                util::buffer_write32be(&buf[13],
                                       (uint32_t) msg->inject_scroll_event.hscroll);
                util::buffer_write32be(&buf[17],
                                       (uint32_t) msg->inject_scroll_event.vscroll);
                return 21;
            case CONTROL_MSG_TYPE_SET_CLIPBOARD: {
                size_t len = WriteString(msg->inject_text.text,
                                         CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH,
                                         &buf[1]);
                return 1 + len;
            }
            case CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE:
                buf[1] = msg->set_screen_power_mode.mode;
                return 2;
            case CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON:
            case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL:
            case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL:
            case CONTROL_MSG_TYPE_GET_CLIPBOARD:
            case CONTROL_MSG_TYPE_ROTATE_DEVICE:
                // no additional data
                return 1;
            default:
                LOGW("Unknown message type: %u", (unsigned) msg->type);
                return 0;
        }
    }


    void ControlMessage::Destroy() {
        struct ControlMessage *msg = this;
        switch (msg->type) {
            case CONTROL_MSG_TYPE_INJECT_TEXT:
                SDL_free(msg->inject_text.text);
                break;
            case CONTROL_MSG_TYPE_SET_CLIPBOARD:
                SDL_free(msg->set_clipboard.text);
                break;
            default:
                // do nothing
                break;
        }
    }


    void ControlMessage::WritePosition(uint8_t *buf, const struct Position *position) {
        util::buffer_write32be(&buf[0], position->point.x);
        util::buffer_write32be(&buf[4], position->point.y);
        util::buffer_write16be(&buf[8], position->screen_size.width);
        util::buffer_write16be(&buf[10], position->screen_size.height);
    }

// write length (2 bytes) + string (non nul-terminated)
    size_t ControlMessage::WriteString(const char *utf8, size_t max_len, unsigned char *buf) {
        size_t len = util::utf8_truncation_index(utf8, max_len);
        util::buffer_write16be(buf, (uint16_t) len);
        memcpy(&buf[2], utf8, len);
        return 2 + len;
    }

    uint16_t ControlMessage::ToFixedPoint16(float f) {
        assert(f >= 0.0f && f <= 1.0f);
        uint32_t u = f * 0x1p16f; // 2^16
        if (u >= 0xffff) {
            u = 0xffff;
        }
        return (uint16_t) u;
    }

}