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

bool
receiver_init(struct receiver *receiver, socket_t control_socket) {
    if (!(receiver->mutex = SDL_CreateMutex())) {
        return false;
    }
    receiver->control_socket = control_socket;
    return true;
}

void
receiver_destroy(struct receiver *receiver) {
    SDL_DestroyMutex(receiver->mutex);
}

static void
process_msg(struct device_msg *msg) {
    switch (msg->type) {
        case DEVICE_MSG_TYPE_CLIPBOARD:
            LOGI("Device clipboard copied");
            SDL_SetClipboardText(msg->clipboard.text);
            break;
    }
}

static ssize_t
process_msgs(const unsigned char *buf, size_t len) {
    size_t head = 0;
    for (;;) {
        struct device_msg msg{};
        ssize_t r = device_msg_deserialize(&buf[head], len - head, &msg);
        if (r == -1) {
            return -1;
        }
        if (r == 0) {
            return head;
        }

        process_msg(&msg);
        device_msg_destroy(&msg);

        head += r;
        assert(head <= len);
        if (head == len) {
            return head;
        }
    }
}

static int
run_receiver(void *data) {
    auto *receiver = (struct receiver *) data;

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

bool
receiver_start(struct receiver *receiver) {
    LOGD("Starting receiver thread");

    receiver->thread = SDL_CreateThread(run_receiver, "receiver", receiver);
    if (!receiver->thread) {
        LOGC("Could not start receiver thread");
        return false;
    }

    return true;
}

void
receiver_join(struct receiver *receiver) {
    SDL_WaitThread(receiver->thread, nullptr);
}
