//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CONTROLLER_HPP
#define ANDROID_IROBOT_CONTROLLER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif


#include "config.hpp"
#include "android/receiver.hpp"
#include "message/control_msg.hpp"
#include "util/cbuf.hpp"
#include "util/net.hpp"

struct control_msg_queue CBUF(struct control_msg, 64);

struct controller {
    socket_t control_socket;
    SDL_Thread *thread;
    SDL_mutex *mutex;
    SDL_cond *msg_cond;
    bool stopped;
    struct control_msg_queue queue;
    struct receiver receiver;
};

bool
controller_init(struct controller *controller, socket_t control_socket);

void
controller_destroy(struct controller *controller);

bool
controller_start(struct controller *controller);

void
controller_stop(struct controller *controller);

void
controller_join(struct controller *controller);

bool
controller_push_msg(struct controller *controller,
                    const struct control_msg *msg);

#endif //ANDROID_IROBOT_CONTROLLER_HPP
