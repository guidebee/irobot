//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "controller.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

bool Controller::init(socket_t control_socket) {
    Controller *controller = this;
    cbuf_init(&this->queue);

    if (!this->receiver.init(control_socket)) {
        return false;
    }

    if (!(this->mutex = SDL_CreateMutex())) {
        this->receiver.destroy();
        return false;
    }

    if (!(this->msg_cond = SDL_CreateCond())) {
        this->receiver.destroy();
        SDL_DestroyMutex(this->mutex);
        return false;
    }

    this->control_socket = control_socket;
    this->stopped = false;

    return true;
}

void Controller::destroy() {
    SDL_DestroyCond(this->msg_cond);
    SDL_DestroyMutex(this->mutex);

    struct ControlMessage msg{};
    while (cbuf_take(&this->queue, &msg)) {
        msg.destroy();
    }

    this->receiver.destroy();
}

bool Controller::push_msg(
        const struct ControlMessage *msg) {
    mutex_lock(this->mutex);
    bool was_empty = cbuf_is_empty(&this->queue);
    bool res = cbuf_push(&this->queue, *msg);
    if (was_empty) {
        cond_signal(this->msg_cond);
    }
    mutex_unlock(this->mutex);
    return res;
}

bool Controller::process_msg(
        struct ControlMessage *msg) {

    unsigned char serialized_msg[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int length = msg->serialize(serialized_msg);
    if (!length) {
        return false;
    }
    int w = net_send_all(this->control_socket, serialized_msg, length);
    return w == length;
}

int Controller::run_controller(void *data) {
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

        bool ok = controller->process_msg(&msg);
        msg.destroy();
        if (!ok) {
            LOGD("Could not write msg to socket");
            break;
        }
    }
    return 0;
}

bool Controller::start() {

    LOGD("Starting controller thread");

    this->thread = SDL_CreateThread(run_controller, "controller",
                                    this);
    if (!this->thread) {
        LOGC("Could not start controller thread");
        return false;
    }

    if (!this->receiver.start()) {
        this->stop();
        SDL_WaitThread(this->thread, nullptr);
        return false;
    }

    return true;
}

void Controller::stop() {
    mutex_lock(this->mutex);
    this->stopped = true;
    cond_signal(this->msg_cond);
    mutex_unlock(this->mutex);
}

void Controller::join() {
    SDL_WaitThread(this->thread, nullptr);
    this->receiver.join();
}

