//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "controller.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

bool
Controller::init(socket_t control_socket) {
    Controller *controller = this;
    cbuf_init(&controller->queue);

    if (!receiver_init(&controller->receiver, control_socket)) {
        return false;
    }

    if (!(controller->mutex = SDL_CreateMutex())) {
        receiver_destroy(&controller->receiver);
        return false;
    }

    if (!(controller->msg_cond = SDL_CreateCond())) {
        receiver_destroy(&controller->receiver);
        SDL_DestroyMutex(controller->mutex);
        return false;
    }

    controller->control_socket = control_socket;
    controller->stopped = false;

    return true;
}

void
Controller::destroy() {
    Controller *controller = this;
    SDL_DestroyCond(controller->msg_cond);
    SDL_DestroyMutex(controller->mutex);

    struct ControlMessage msg{};
    while (cbuf_take(&controller->queue, &msg)) {
        msg.destroy();
    }

    receiver_destroy(&controller->receiver);
}

bool
Controller::push_msg(
        const struct ControlMessage *msg) {
    Controller *controller = this;
    mutex_lock(controller->mutex);
    bool was_empty = cbuf_is_empty(&controller->queue);
    bool res = cbuf_push(&controller->queue, *msg);
    if (was_empty) {
        cond_signal(controller->msg_cond);
    }
    mutex_unlock(controller->mutex);
    return res;
}

static bool
process_msg(Controller *controller,
        struct ControlMessage *msg) {

    unsigned char serialized_msg[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int length = msg->serialize(serialized_msg);
    if (!length) {
        return false;
    }
    int w = net_send_all(controller->control_socket, serialized_msg, length);
    return w == length;
}

static int
run_controller(void *data) {
    auto *controller = static_cast<Controller *>(data);

    for (;;) {
        mutex_lock(controller->mutex);
        while (!controller->stopped && cbuf_is_empty(&controller->queue)) {
            cond_wait(controller->msg_cond, controller->mutex);
        }
        if (controller->stopped) {
            // stop immediately, do not process further msgs
            mutex_unlock(controller->mutex);
            break;
        }
        struct ControlMessage msg{};
        bool non_empty = cbuf_take(&controller->queue, &msg);
        assert(non_empty);
        (void) non_empty;
        mutex_unlock(controller->mutex);

        bool ok = process_msg(controller, &msg);
        msg.destroy();
        if (!ok) {
            LOGD("Could not write msg to socket");
            break;
        }
    }
    return 0;
}

bool
Controller::start() {
    Controller *controller = this;
    LOGD("Starting controller thread");

    controller->thread = SDL_CreateThread(run_controller, "controller",
                                          controller);
    if (!controller->thread) {
        LOGC("Could not start controller thread");
        return false;
    }

    if (!receiver_start(&controller->receiver)) {
        controller->stop();
        SDL_WaitThread(controller->thread, nullptr);
        return false;
    }

    return true;
}

void
Controller::stop() {
    Controller *controller = this;
    mutex_lock(controller->mutex);
    controller->stopped = true;
    cond_signal(controller->msg_cond);
    mutex_unlock(controller->mutex);
}

void
Controller::join() {
    Controller *controller = this;
    SDL_WaitThread(controller->thread, nullptr);
    receiver_join(&controller->receiver);
}

