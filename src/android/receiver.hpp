//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_RECEIVER_HPP
#define ANDROID_IROBOT_RECEIVER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "util/net.hpp"


// receive events from the device
// managed by the controller
class Receiver {
public:
    socket_t control_socket;
    SDL_Thread *thread;
    SDL_mutex *mutex;

    bool init(socket_t control_socket);

    void destroy();

    bool start();

    // no receiver_stop(), it will automatically stop on control_socket shutdown

    void join();
};


#endif //ANDROID_IROBOT_RECEIVER_HPP
