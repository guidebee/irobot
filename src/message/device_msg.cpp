//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "device_msg.hpp"

#include "util/buffer_util.hpp"
#include "util/log.hpp"

namespace irobot::message
{
    ssize_t DeviceMessage::Deserialize(const unsigned char* buf,
                                       size_t len)
    {
        struct DeviceMessage* msg = this;
        if (len < 1)
        {
            return 0; // not available
        }

        uint8_t type_byte = buf[0];
        msg->type = DEVICE_MSG_TYPE_CLIPBOARD; // safe default

        switch (type_byte)
        {
        case 0:
            {
                // TYPE_CLIPBOARD: [1 type][4 length][N text]
                msg->type = DEVICE_MSG_TYPE_CLIPBOARD;
                if (len < 5) return 0;
                uint32_t clipboard_len = util::buffer_read32be(&buf[1]);
                if (clipboard_len > len - 5)
                {
                    return 0; // not available yet
                }
                char* text = (char*)SDL_malloc(clipboard_len + 1);
                if (!text)
                {
                    LOGW("Could not allocate text for clipboard");
                    return -1;
                }
                if (clipboard_len)
                {
                    memcpy(text, &buf[5], clipboard_len);
                }
                text[clipboard_len] = '\0';
                msg->clipboard.text = text;
                return 5 + clipboard_len;
            }
        case 1:
            {
                // TYPE_ACK_CLIPBOARD: [1 type][8 sequence]
                if (len < 9) return 0;
                msg->type = DEVICE_MSG_TYPE_ACK_CLIPBOARD;
                return 9;
            }
        case 2:
            {
                // TYPE_UHID_OUTPUT: [1 type][2 id][2 size][N data]
                if (len < 5) return 0;
                uint16_t data_len = util::buffer_read16be(&buf[3]);
                if ((size_t)(5 + data_len) > len) return 0;
                msg->type = DEVICE_MSG_TYPE_UHID_OUTPUT;
                return 5 + data_len;
            }
        default:
            LOGW("Unknown device message type: %d", (int)type_byte);
            return -1; // error, we cannot recover
        }
    }

    void DeviceMessage::Destroy()
    {
        if (this->type == DEVICE_MSG_TYPE_CLIPBOARD)
        {
            SDL_free(this->clipboard.text);
        }
    }
}