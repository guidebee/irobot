//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "fps_counter.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

#define FPS_COUNTER_INTERVAL_MS 1000

bool FpsCounter::init() {
    this->mutex = SDL_CreateMutex();
    if (!this->mutex) {
        return false;
    }

    this->state_cond = SDL_CreateCond();
    if (!this->state_cond) {
        SDL_DestroyMutex(this->mutex);
        return false;
    }

    this->thread = nullptr;
    SDL_AtomicSet(&this->started, 0);
    // no need to initialize the other fields, they are unused until started

    return true;
}

void FpsCounter::destroy() {
    SDL_DestroyCond(this->state_cond);
    SDL_DestroyMutex(this->mutex);
}

// must be called with mutex locked
void FpsCounter::display_fps() {
    unsigned rendered_per_second =
            this->nr_rendered * 1000 / FPS_COUNTER_INTERVAL_MS;
    if (this->nr_skipped) {
        LOGI("%u fps (+%u frames skipped)", rendered_per_second,
             this->nr_skipped);
    } else {
        LOGI("%u fps", rendered_per_second);
    }
}

// must be called with mutex locked
void FpsCounter::check_interval_expired(uint32_t now) {
    if (now < this->next_timestamp) {
        return;
    }

    this->display_fps();
    this->nr_rendered = 0;
    this->nr_skipped = 0;
    // add a multiple of the interval
    uint32_t elapsed_slices =
            (now - this->next_timestamp) / FPS_COUNTER_INTERVAL_MS + 1;
    this->next_timestamp += FPS_COUNTER_INTERVAL_MS * elapsed_slices;
}

int FpsCounter::run_fps_counter(void *data) {
    auto *counter = (struct FpsCounter *) data;

    mutex_lock(counter->mutex);
    while (!counter->interrupted) {
        while (!counter->interrupted && !SDL_AtomicGet(&counter->started)) {
            cond_wait(counter->state_cond, counter->mutex);
        }
        while (!counter->interrupted && SDL_AtomicGet(&counter->started)) {
            uint32_t now = SDL_GetTicks();
            counter->check_interval_expired(now);

            assert(counter->next_timestamp > now);
            uint32_t remaining = counter->next_timestamp - now;

            // ignore the reason (timeout or signaled), we just loop anyway
            cond_wait_timeout(counter->state_cond, counter->mutex, remaining);
        }
    }
    mutex_unlock(counter->mutex);
    return 0;
}

bool FpsCounter::start() {
    mutex_lock(this->mutex);
    this->next_timestamp = SDL_GetTicks() + FPS_COUNTER_INTERVAL_MS;
    this->nr_rendered = 0;
    this->nr_skipped = 0;
    mutex_unlock(this->mutex);
    SDL_AtomicSet(&this->started, 1);
    cond_signal(this->state_cond);

    // this->thread is always accessed from the same thread, no need to lock
    if (!this->thread) {
        this->thread =
                SDL_CreateThread(run_fps_counter, "fps counter", this);
        if (!this->thread) {
            LOGE("Could not start FPS counter thread");
            return false;
        }
    }

    return true;
}

void FpsCounter::stop() {
    SDL_AtomicSet(&this->started, 0);
    cond_signal(this->state_cond);
}

bool FpsCounter::is_started() {
    return SDL_AtomicGet(&this->started) == 1;
}

void FpsCounter::interrupt() {
    if (!this->thread) {
        return;
    }

    mutex_lock(this->mutex);
    this->interrupted = true;
    mutex_unlock(this->mutex);
    // wake up blocking wait
    cond_signal(this->state_cond);
}

void FpsCounter::join() {
    if (this->thread) {
        SDL_WaitThread(this->thread, nullptr);
    }
}

void FpsCounter::add_rendered_frame() {
    if (!SDL_AtomicGet(&this->started)) {
        return;
    }

    mutex_lock(this->mutex);
    uint32_t now = SDL_GetTicks();
    this->check_interval_expired(now);
    ++this->nr_rendered;
    mutex_unlock(this->mutex);
}

void FpsCounter::add_skipped_frame() {
    if (!SDL_AtomicGet(&this->started)) {
        return;
    }
    mutex_lock(this->mutex);
    uint32_t now = SDL_GetTicks();
    this->check_interval_expired(now);
    ++this->nr_skipped;
    mutex_unlock(this->mutex);
}
