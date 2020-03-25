//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "device_msg.hpp"

#include "util/buffer_util.hpp"
#include "util/log.hpp"

ssize_t
device_msg_deserialize(const unsigned char *buf, size_t len,
                       struct device_msg *msg) {
    if (len < 3) {
        // at least type + empty string length
        return 0; // not available
    }

    msg->type = (enum device_msg_type) buf[0];
    switch (msg->type) {
        case DEVICE_MSG_TYPE_CLIPBOARD: {
            uint16_t clipboard_len = buffer_read16be(&buf[1]);
            if (clipboard_len > len - 3) {
                return 0; // not available
            }
            char *text = (char *) SDL_malloc(clipboard_len + 1);
            if (!text) {
                LOGW("Could not allocate text for clipboard");
                return -1;
            }
            if (clipboard_len) {
                memcpy(text, &buf[3], clipboard_len);
            }
            text[clipboard_len] = '\0';

            msg->clipboard.text = text;
            return 3 + clipboard_len;
        }
        default:
            LOGW("Unknown device message type: %d", (int) msg->type);
            return -1; // error, we cannot recover
    }
}

void
device_msg_destroy(struct device_msg *msg) {
    if (msg->type == DEVICE_MSG_TYPE_CLIPBOARD) {
        SDL_free(msg->clipboard.text);
    }
}
