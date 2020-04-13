//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "receiver.hpp"

#include <SDL2/SDL_clipboard.h>

#include <cassert>
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
        unsigned char buf[DEVICE_NAME_FIELD_LENGTH + 4];
        int r = platform::net_recv_all(device_socket, buf, sizeof(buf));
        if (r < DEVICE_NAME_FIELD_LENGTH + 4) {
            LOGE("Could not retrieve device information");
            return false;
        }
        // in case the client sends garbage
        buf[DEVICE_NAME_FIELD_LENGTH - 1] = '\0';
        // strcpy is safe here, since name contains at least
        // DEVICE_NAME_FIELD_LENGTH bytes and strlen(buf) < DEVICE_NAME_FIELD_LENGTH
        strcpy(device_name, (char *) buf);
        size->width = (static_cast<unsigned char>(buf[DEVICE_NAME_FIELD_LENGTH] << 8))
                      | buf[DEVICE_NAME_FIELD_LENGTH + 1];
        size->height = (static_cast<unsigned char>(buf[DEVICE_NAME_FIELD_LENGTH + 2] << 8))
                       | buf[DEVICE_NAME_FIELD_LENGTH + 3];
        return true;
    }
}