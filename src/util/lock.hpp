//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_LOCK_HPP
#define ANDROID_IROBOT_LOCK_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_mutex.h>

#if defined (__cplusplus)
}
#endif

#include <cstdint>

#include "config.hpp"
#include "log.hpp"


namespace irobot::util {

    static inline void mutex_log(int r, const char *message) {
#ifndef NDEBUG
        if (r) {
            LOGC("%s: %s", message, SDL_GetError());
            abort();
        }
#else
        (void) r;
#endif
    }

    static inline void mutex_lock(SDL_mutex *mutex) {
        int r = SDL_LockMutex(mutex);
        mutex_log(r, "Could not unlock mutex");
    }


    static inline void mutex_unlock(SDL_mutex *mutex) {
        int r = SDL_UnlockMutex(mutex);
        mutex_log(r, "Could not unlock mutex");
    }

    static inline void cond_wait(SDL_cond *cond, SDL_mutex *mutex) {
        int r = SDL_CondWait(cond, mutex);
        mutex_log(r, "Could not wait on condition");
    }

    static inline int cond_wait_timeout(SDL_cond *cond,
                                        SDL_mutex *mutex, uint32_t ms) {
        int r = SDL_CondWaitTimeout(cond, mutex, ms);
        return r;
    }

    static inline void cond_signal(SDL_cond *cond) {
        int r = SDL_CondSignal(cond);
        mutex_log(r, "Could not signal a condition");
    }

}
#endif //ANDROID_IROBOT_LOCK_HPP
