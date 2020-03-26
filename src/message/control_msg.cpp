//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//
#pragma clang diagnostic push
#pragma ide diagnostic ignored "modernize-use-nullptr"
#pragma ide diagnostic ignored "modernize-raw-string-literal"

#include <cassert>
#include <cstring>

#if defined (__cplusplus)
extern "C" {
#endif


#include <sys/time.h>

#if defined (__cplusplus)
}
#endif

#include "control_msg.hpp"

#include "util/buffer_util.hpp"
#include "util/log.hpp"
#include "util/str_util.hpp"


static void
write_position(uint8_t *buf, const struct position *position) {
    buffer_write32be(&buf[0], position->point.x);
    buffer_write32be(&buf[4], position->point.y);
    buffer_write16be(&buf[8], position->screen_size.width);
    buffer_write16be(&buf[10], position->screen_size.height);
}

// write length (2 bytes) + string (non nul-terminated)
static size_t
write_string(const char *utf8, size_t max_len, unsigned char *buf) {
    size_t len = utf8_truncation_index(utf8, max_len);
    buffer_write16be(buf, (uint16_t) len);
    memcpy(&buf[2], utf8, len);
    return 2 + len;
}

static uint16_t
to_fixed_point_16(float f) {
    assert(f >= 0.0f && f <= 1.0f);
    uint32_t u = f * 0x1p16f; // 2^16
    if (u >= 0xffff) {
        u = 0xffff;
    }
    return (uint16_t) u;
}

size_t
control_msg_serialize(const struct control_msg *msg, unsigned char *buf) {
    buf[0] = msg->type;
    switch (msg->type) {
        case CONTROL_MSG_TYPE_INJECT_KEYCODE:
            buf[1] = msg->inject_keycode.action;
            buffer_write32be(&buf[2], msg->inject_keycode.keycode);
            buffer_write32be(&buf[6], msg->inject_keycode.metastate);
            return 10;
        case CONTROL_MSG_TYPE_INJECT_TEXT: {
            size_t len = write_string(msg->inject_text.text,
                                      CONTROL_MSG_TEXT_MAX_LENGTH, &buf[1]);
            return 1 + len;
        }
        case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: {
            buf[1] = msg->inject_touch_event.action;
            buffer_write64be(&buf[2], msg->inject_touch_event.pointer_id);
            write_position(&buf[10], &msg->inject_touch_event.position);
            uint16_t pressure =
                    to_fixed_point_16(msg->inject_touch_event.pressure);
            buffer_write16be(&buf[22], pressure);
            buffer_write32be(&buf[24], msg->inject_touch_event.buttons);
            return 28;
        }
        case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
            write_position(&buf[1], &msg->inject_scroll_event.position);
            buffer_write32be(&buf[13],
                             (uint32_t) msg->inject_scroll_event.hscroll);
            buffer_write32be(&buf[17],
                             (uint32_t) msg->inject_scroll_event.vscroll);
            return 21;
        case CONTROL_MSG_TYPE_SET_CLIPBOARD: {
            size_t len = write_string(msg->inject_text.text,
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


void
control_msg_destroy(struct control_msg *msg) {
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


char *
control_msg_json_serialize(const struct control_msg *msg) {
    char *buffer = (char *) SDL_malloc(CONTROL_MSG_SERIALIZED_MAX_SIZE);
    if (buffer != NULL) {
        char temp[256];

        strcpy(buffer, "{\n");
        sprintf(temp, "    \"event_time\" : \"");
        strcat(buffer, temp);
        struct timeval tm_now;
        int milli_seconds;
        gettimeofday(&tm_now, NULL);
        milli_seconds = lrint(tm_now.tv_usec / 1000.0); // Round to nearest milli seconds
        if (milli_seconds >= 1000) { // Allow for rounding up to nearest second
            milli_seconds -= 1000;
            tm_now.tv_sec++;
        }
        struct tm *t = localtime(&tm_now.tv_sec);
        strftime(temp, sizeof(temp) - 1, "%Y-%m-%d %H:%M:%S", t);
        strcat(buffer, temp);
        strcat(buffer, ".");
        sprintf(temp, "%03d", milli_seconds);
        strcat(buffer, temp);
        strcat(buffer, "\",\n");

        switch (msg->type) {
            case CONTROL_MSG_TYPE_INJECT_KEYCODE: {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_KEYCODE");
                strcat(buffer, temp);
                sprintf(temp, "    \"key_code\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"action\" : %d,\n", msg->inject_keycode.action);
                strcat(buffer, temp);
                sprintf(temp, "        \"key_code\" : %d,\n", msg->inject_keycode.keycode);
                strcat(buffer, temp);
                sprintf(temp, "        \"meta_state\" : %d\n", msg->inject_keycode.metastate);
                strcat(buffer, temp);
                strcat(buffer, "    }\n");
            }
                break;
            case CONTROL_MSG_TYPE_INJECT_TEXT: {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_TEXT");
                strcat(buffer, temp);
                sprintf(temp, "    \"inject_text\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"text\" : \"%s\"\n", msg->inject_text.text);
                strcat(buffer, temp);
                strcat(buffer, "    }\n");
            }
                break;
            case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL: {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL");
                strcat(buffer, temp);
            }
                break;
            case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL: {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL");
                strcat(buffer, temp);
            }
                break;
            case CONTROL_MSG_TYPE_ROTATE_DEVICE: {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_ROTATE_DEVICE");
                strcat(buffer, temp);
            }
                break;

            case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT");
                strcat(buffer, temp);
                sprintf(temp, "    \"touch_event\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"action\" : %d,\n", msg->inject_touch_event.action);
                strcat(buffer, temp);
                sprintf(temp, "        \"buttons\" : %d,\n", msg->inject_touch_event.buttons);
                strcat(buffer, temp);
                sprintf(temp, "        \"pointer\" : %lld,\n", msg->inject_touch_event.pointer_id);
                strcat(buffer, temp);
                sprintf(temp, "        \"pressure\" : %f,\n", msg->inject_touch_event.pressure);
                strcat(buffer, temp);
                sprintf(temp, "        \"position\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "            \"screen_size\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"width\" : %d,\n", msg->inject_touch_event.position.screen_size.width);
                strcat(buffer, temp);
                sprintf(temp, "                \"height\" : %d\n", msg->inject_touch_event.position.screen_size.height);
                strcat(buffer, temp);
                strcat(buffer, "            },\n");
                sprintf(temp, "            \"point\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"x\" : %d,\n", msg->inject_touch_event.position.point.x);
                strcat(buffer, temp);
                sprintf(temp, "                \"y\" : %d\n", msg->inject_touch_event.position.point.y);
                strcat(buffer, temp);

                strcat(buffer, "            }\n");
                strcat(buffer, "        }\n");
                strcat(buffer, "    }\n");
            }
                break;
            case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT: {

                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT");
                strcat(buffer, temp);
                sprintf(temp, "    \"scroll_event\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"h_scroll\" : %d,\n", msg->inject_scroll_event.hscroll);
                strcat(buffer, temp);
                sprintf(temp, "        \"v_scroll\" : %d,\n", msg->inject_scroll_event.vscroll);
                strcat(buffer, temp);
                sprintf(temp, "        \"position\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "            \"screen_size\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"width\" : %d,\n", msg->inject_touch_event.position.screen_size.width);
                strcat(buffer, temp);
                sprintf(temp, "                \"height\" : %d\n", msg->inject_touch_event.position.screen_size.height);
                strcat(buffer, temp);
                strcat(buffer, "            },\n");
                sprintf(temp, "            \"point\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"x\" : %d,\n", msg->inject_touch_event.position.point.x);
                strcat(buffer, temp);
                sprintf(temp, "                \"y\" : %d\n", msg->inject_touch_event.position.point.y);
                strcat(buffer, temp);

                strcat(buffer, "            }\n");
                strcat(buffer, "        }\n");
                strcat(buffer, "    }\n");
            }
                break;
            default:
                break;

        }
        strcat(buffer, "},\n");
        return buffer;
    }
    return NULL;
}




