//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "receiver.hpp"

#if defined (__cplusplus)
extern "C" {
#endif
#include <SDL2/SDL_clipboard.h>

#if defined (__cplusplus)
}
#endif

#include <cassert>

#include "message/device_msg.hpp"
#include "util/lock.hpp"
#include "util/log.hpp"

bool Receiver::init(socket_t control_socket) {
    Receiver *receiver = this;
    if (!(receiver->mutex = SDL_CreateMutex())) {
        return false;
    }
    receiver->control_socket = control_socket;
    return true;
}

void Receiver::destroy() {
    Receiver *receiver = this;
    SDL_DestroyMutex(receiver->mutex);
}

void Receiver::process_msg(struct DeviceMessage *msg) {
    switch (msg->type) {
        case DEVICE_MSG_TYPE_CLIPBOARD:
            LOGI("Device clipboard copied");
            SDL_SetClipboardText(msg->clipboard.text);
            break;
    }
}


bool Receiver::start() {
    Receiver *receiver = this;
    LOGD("Starting receiver thread");

    receiver->thread = SDL_CreateThread(Receiver::run_receiver, "receiver", receiver);
    if (!receiver->thread) {
        LOGC("Could not start receiver thread");
        return false;
    }

    return true;
}

void Receiver::join() {
    Receiver *receiver = this;
    SDL_WaitThread(receiver->thread, nullptr);
}


ssize_t Receiver::process_msgs(const unsigned char *buf, size_t len) {
    size_t head = 0;
    for (;;) {
        struct DeviceMessage msg{};
        ssize_t r = msg.deserialize(&buf[head], len - head);
        if (r == -1) {
            return -1;
        }
        if (r == 0) {
            return head;
        }

        process_msg(&msg);
        msg.destroy();

        head += r;
        assert(head <= len);
        if (head == len) {
            return head;
        }
    }
}

int Receiver::run_receiver(void *data) {
    auto *receiver = (Receiver *) data;

    unsigned char buf[DEVICE_MSG_SERIALIZED_MAX_SIZE];
    size_t head = 0;

    for (;;) {
        assert(head < DEVICE_MSG_SERIALIZED_MAX_SIZE);
        ssize_t r = net_recv(receiver->control_socket, buf,
                             DEVICE_MSG_SERIALIZED_MAX_SIZE - head);
        if (r <= 0) {
            LOGD("Receiver stopped");
            break;
        }

        ssize_t consumed = process_msgs(buf, r);
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
