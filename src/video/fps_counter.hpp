//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_FPS_COUNTER_HPP
#define ANDROID_IROBOT_FPS_COUNTER_HPP

#include <cstdint>

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_atomic.h>
#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>
#include <SDL2/SDL_timer.h>

#if defined (__cplusplus)
}
#endif


#include "config.hpp"

namespace irobot::video {
    class FpsCounter {
    public:
        SDL_Thread *thread;
        SDL_mutex *mutex;
        SDL_cond *state_cond;

        // atomic so that we can check without locking the mutex
        // if the FPS counter is disabled, we don't want to lock unnecessarily
        SDL_atomic_t started;

        // the following fields are protected by the mutex
        bool interrupted;
        unsigned nr_rendered;
        unsigned nr_skipped;
        uint32_t next_timestamp;


        bool Init();

        void Destroy();

        bool Start();

        void Stop();

        bool IsStarted();

        // request to stop the thread (on quit)
        // must be called before fps_counter_join()
        void Interrupt();

        void Join();

        void AddRenderedFrame();

        void AddSkippedFrame();

        void CheckIntervalExpired(uint32_t now);

        static int RunFpsCounter(void *data);

    private:
        void display_fps();


    };

}
#endif //ANDROID_IROBOT_FPS_COUNTER_HPP
