//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_RECEIVER_HPP
#define ANDROID_IROBOT_RECEIVER_HPP

#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#include "config.hpp"
#include "util/net.hpp"


// receive events from the device
// managed by the controller
struct receiver {
    socket_t control_socket;
    SDL_Thread *thread;
    SDL_mutex *mutex;
};

bool
receiver_init(struct receiver *receiver, socket_t control_socket);

void
receiver_destroy(struct receiver *receiver);

bool
receiver_start(struct receiver *receiver);

// no receiver_stop(), it will automatically stop on control_socket shutdown

void
receiver_join(struct receiver *receiver);

#endif //ANDROID_IROBOT_RECEIVER_HPP
