//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_FPS_COUNTER_HPP
#define ANDROID_IROBOT_FPS_COUNTER_HPP

#include <cstdint>
#include <SDL2/SDL_atomic.h>
#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>
#include "config.hpp"

struct fps_counter {
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
};

bool
fps_counter_init(struct fps_counter *counter);

void
fps_counter_destroy(struct fps_counter *counter);

bool
fps_counter_start(struct fps_counter *counter);

void
fps_counter_stop(struct fps_counter *counter);

bool
fps_counter_is_started(struct fps_counter *counter);

// request to stop the thread (on quit)
// must be called before fps_counter_join()
void
fps_counter_interrupt(struct fps_counter *counter);

void
fps_counter_join(struct fps_counter *counter);

void
fps_counter_add_rendered_frame(struct fps_counter *counter);

void
fps_counter_add_skipped_frame(struct fps_counter *counter);
#endif //ANDROID_IROBOT_FPS_COUNTER_HPP
