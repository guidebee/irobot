//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "fps_counter.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

#define FPS_COUNTER_INTERVAL_MS 1000
namespace irobot::video {


    bool FpsCounter::Init() {
        bool initialzed=Actor::Init();
        if (!initialzed) {
            return false;
        }

        SDL_AtomicSet(&this->started, 0);
        // no need to initialize the other fields, they are unused until started
        return true;
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
    void FpsCounter::CheckIntervalExpired(uint32_t now) {
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

    int FpsCounter::RunFpsCounter(void *data) {
        auto *counter = (struct FpsCounter *) data;

        util::mutex_lock(counter->mutex);
        while (!counter->interrupted) {
            while (!counter->interrupted && !SDL_AtomicGet(&counter->started)) {
                util::cond_wait(counter->thread_cond, counter->mutex);
            }
            while (!counter->interrupted && SDL_AtomicGet(&counter->started)) {
                uint32_t now = SDL_GetTicks();
                counter->CheckIntervalExpired(now);

                assert(counter->next_timestamp > now);
                uint32_t remaining = counter->next_timestamp - now;

                // ignore the reason (timeout or signaled), we just loop anyway
                util::cond_wait_timeout(counter->thread_cond, counter->mutex, remaining);
            }
        }
        util::mutex_unlock(counter->mutex);
        return 0;
    }

    bool FpsCounter::Start() {
        util::mutex_lock(this->mutex);
        this->next_timestamp = SDL_GetTicks() + FPS_COUNTER_INTERVAL_MS;
        this->nr_rendered = 0;
        this->nr_skipped = 0;
        util::mutex_unlock(this->mutex);
        SDL_AtomicSet(&this->started, 1);
        util::cond_signal(this->thread_cond);

        // this->thread is always accessed from the same thread, no need to lock
        if (!this->thread) {
            this->thread =
                    SDL_CreateThread(RunFpsCounter, "fps counter", this);
            if (!this->thread) {
                LOGE("Could not start FPS counter thread");
                return false;
            }
        }

        return true;
    }

    void FpsCounter::Stop() {
        SDL_AtomicSet(&this->started, 0);
        Actor::Stop();
    }

    bool FpsCounter::IsStarted() {
        return SDL_AtomicGet(&this->started) == 1;
    }

    void FpsCounter::Interrupt() {
        if (!this->thread) {
            return;
        }
        util::mutex_lock(this->mutex);
        this->interrupted = true;
        util::mutex_unlock(this->mutex);
        // wake up blocking wait
        util::cond_signal(this->thread_cond);
    }

    void FpsCounter::AddRenderedFrame() {
        if (!SDL_AtomicGet(&this->started)) {
            return;
        }

        util::mutex_lock(this->mutex);
        uint32_t now = SDL_GetTicks();
        this->CheckIntervalExpired(now);
        ++this->nr_rendered;
        util::mutex_unlock(this->mutex);
    }

    void FpsCounter::AddSkippedFrame() {
        if (!SDL_AtomicGet(&this->started)) {
            return;
        }
        util::mutex_lock(this->mutex);
        uint32_t now = SDL_GetTicks();
        this->CheckIntervalExpired(now);
        ++this->nr_skipped;
        util::mutex_unlock(this->mutex);
    }
}