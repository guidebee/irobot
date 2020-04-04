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

namespace irobot {



    struct ControlMessageQueue CBUF(struct message::ControlMessage, 64);


    class Controller {
    public:
        socket_t control_socket;
        SDL_Thread *thread;
        SDL_mutex *mutex;
        SDL_cond *msg_cond;
        bool stopped;
        struct ControlMessageQueue queue;

        class android::Receiver receiver;

        bool Init(socket_t control_socket);

        void Destroy();

        bool Start();

        void Stop();

        void Join();

        bool PushMessage(const struct message::ControlMessage *msg);

        static int RunController(void *data);

    private:
        bool ProcessMessage(struct message::ControlMessage *msg);

    };
}

#endif //ANDROID_IROBOT_CONTROLLER_HPP
