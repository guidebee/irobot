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
#include "platform/net.hpp"

struct ControlMessageQueue CBUF(struct ControlMessage, 64);


class Controller {
public:
    socket_t control_socket;
    SDL_Thread *thread;
    SDL_mutex *mutex;
    SDL_cond *msg_cond;
    bool stopped;
    struct ControlMessageQueue queue;

    class Receiver receiver;

    bool init(socket_t control_socket);

    void destroy();

    bool start();

    void stop();

    void join();

    bool push_msg(const struct ControlMessage *msg);

    static int run_controller(void *data);

private:
    bool process_msg(struct ControlMessage *msg);

};

#endif //ANDROID_IROBOT_CONTROLLER_HPP
