//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_ACTOR_HPP
#define ANDROID_IROBOT_ACTOR_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif

namespace irobot {

    class Actor {

    public:

        SDL_Thread *thread;
        SDL_mutex *mutex;
        SDL_cond *msg_cond;
        bool stopped;

        virtual bool Init();

        virtual void Destroy();

        virtual bool Start() = 0;

        virtual void Stop();

        virtual void Join();

    };

}
#endif //ANDROID_IROBOT_ACTOR_HPP
