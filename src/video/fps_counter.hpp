//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_FPS_COUNTER_HPP
#define ANDROID_IROBOT_FPS_COUNTER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_atomic.h>
#include <SDL2/SDL_timer.h>

#if defined (__cplusplus)
}
#endif

#include <cstdint>
#include "config.hpp"
#include "core/actor.hpp"

namespace irobot::video {

    class FpsCounter : public Actor {

    public:

        // atomic so that we can check without locking the mutex
        // if the FPS counter is disabled, we don't want to lock unnecessarily
        SDL_atomic_t started{};

        // the following fields are protected by the mutex
        bool interrupted = false;
        unsigned nr_rendered = 0;
        unsigned nr_skipped = 0;
        uint32_t next_timestamp = 0;

        bool Init() override;

        bool Start() override;

        void Stop() override;

        bool IsStarted();

        // request to stop the thread (on quit)
        // must be called before fps_counter_join()
        void Interrupt();

        void AddRenderedFrame();

        void AddSkippedFrame();

        void CheckIntervalExpired(uint32_t now);

        static int RunFpsCounter(void *data);

    private:
        void display_fps();

    };

}
#endif //ANDROID_IROBOT_FPS_COUNTER_HPP
