//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "receiver.hpp"

#include <SDL2/SDL_clipboard.h>

#include <cassert>
#include "util/buffer_util.hpp"
#include "util/log.hpp"

namespace irobot::android {

    bool Receiver::Init(socket_t socket) {
        bool initialized = Actor::Init();
        if (!initialized) {
            return false;
        }
        this->control_socket = socket;
        return true;
    }

    void Receiver::ProcessMessage(struct message::DeviceMessage *msg) {
        switch (msg->type) {
            case message::DEVICE_MSG_TYPE_CLIPBOARD:
                LOGI("Device clipboard copied");
                SDL_SetClipboardText(msg->clipboard.text);
                break;
            case message::DEVICE_MSG_TYPE_ACK_CLIPBOARD:
            case message::DEVICE_MSG_TYPE_UHID_OUTPUT:
                // not used by this client
                break;
        }
    }

    bool Receiver::Start() {

        LOGD("Starting receiver thread");
        this->thread = SDL_CreateThread(Receiver::RunReceiver,
                                        "receiver", this);
        if (!this->thread) {
            LOGC("Could not start receiver thread");
            return false;
        }
        return true;
    }


    ssize_t Receiver::ProcessMessages(const unsigned char *buf, size_t len) {
        size_t head = 0;
        for (;;) {
            struct message::DeviceMessage msg{};
            ssize_t r = msg.Deserialize(&buf[head], len - head);
            if (r == -1) {
                return -1;
            }
            if (r == 0) {
                return head;
            }

            ProcessMessage(&msg);
            msg.Destroy();

            head += r;
            assert(head <= len);
            if (head == len) {
                return head;
            }
        }
    }

    int Receiver::RunReceiver(void *data) {
        auto *receiver = (Receiver *) data;
        unsigned char buf[DEVICE_MSG_SERIALIZED_MAX_SIZE];
        size_t head = 0;

        for (;;) {
            assert(head < DEVICE_MSG_SERIALIZED_MAX_SIZE);
            ssize_t r = platform::net_recv(receiver->control_socket, buf,
                                           DEVICE_MSG_SERIALIZED_MAX_SIZE - head);
            if (r <= 0) {
                LOGD("Receiver stopped");
                break;
            }

            ssize_t consumed = ProcessMessages(buf, r);
            if (consumed == -1) {
                // an error occurred
                break;
            }

            if (consumed) {
                // shift the remaining data in the buffer
                memmove(buf, &buf[consumed], r - consumed);
                head = r - consumed;
            }
        }

        return 0;
    }

    bool Receiver::ReadDeviceInfomation(socket_t device_socket,
                                        char *device_name, struct Size *size) {
        // The server sends, in order on the video socket:
        //   1) sendDeviceMeta(): 64-byte device name (null-padded)
        //   2) writeVideoHeader(): 4-byte codec ID
        //   3) writeSessionMeta(): 12-byte session header [flags(4)][width(4)][height(4)]
        //      — flags MSB is always 1 (PACKET_FLAG_SESSION)

        uint8_t name_buf[DEVICE_NAME_FIELD_LENGTH];
        int r = platform::net_recv_all(device_socket, name_buf, DEVICE_NAME_FIELD_LENGTH);
        if (r < DEVICE_NAME_FIELD_LENGTH) {
            LOGE("Could not read device name");
            return false;
        }
        name_buf[DEVICE_NAME_FIELD_LENGTH - 1] = '\0';
        strncpy(device_name, (char *) name_buf, DEVICE_NAME_FIELD_LENGTH);

        uint8_t codec_buf[4];
        r = platform::net_recv_all(device_socket, codec_buf, 4);
        if (r < 4) {
            LOGE("Could not read codec ID");
            return false;
        }
        LOGD("Video codec ID: 0x%08x", util::buffer_read32be(codec_buf));

        uint8_t session_buf[12];
        r = platform::net_recv_all(device_socket, session_buf, 12);
        if (r < 12) {
            LOGE("Could not read session header");
            return false;
        }
        if (!(session_buf[0] & 0x80)) {
            LOGE("Expected session header (MSB=1), got media packet");
            return false;
        }
        size->width  = util::buffer_read32be(&session_buf[4]);
        size->height = util::buffer_read32be(&session_buf[8]);
        return true;
    }
}