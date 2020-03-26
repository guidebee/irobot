//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_LOCK_HPP
#define ANDROID_IROBOT_LOCK_HPP

#include <cstdint>
#include <SDL2/SDL_mutex.h>
#include "log.hpp"
#include "config.hpp"

static inline void
mutex_lock(SDL_mutex *mutex) {
    int r = SDL_LockMutex(mutex);
#ifndef NDEBUG
    if (r) {
        LOGC("Could not lock mutex: %s", SDL_GetError());
        abort();
    }
#else
    (void) r;
#endif
}

static inline void
mutex_unlock(SDL_mutex *mutex) {
    int r = SDL_UnlockMutex(mutex);
#ifndef NDEBUG
    if (r) {
        LOGC("Could not unlock mutex: %s", SDL_GetError());
        abort();
    }
#else
    (void) r;
#endif
}

static inline void
cond_wait(SDL_cond *cond, SDL_mutex *mutex) {
    int r = SDL_CondWait(cond, mutex);
#ifndef NDEBUG
    if (r) {
        LOGC("Could not wait on condition: %s", SDL_GetError());
        abort();
    }
#else
    (void) r;
#endif
}

static inline int
cond_wait_timeout(SDL_cond *cond, SDL_mutex *mutex, uint32_t ms) {
    int r = SDL_CondWaitTimeout(cond, mutex, ms);
#ifndef NDEBUG
    if (r < 0) {
        LOGC("Could not wait on condition with timeout: %s", SDL_GetError());
        abort();
    }
#endif
    return r;
}

static inline void
cond_signal(SDL_cond *cond) {
    int r = SDL_CondSignal(cond);
#ifndef NDEBUG
    if (r) {
        LOGC("Could not signal a condition: %s", SDL_GetError());
        abort();
    }
#else
    (void) r;
#endif
}

#endif //ANDROID_IROBOT_LOCK_HPP
