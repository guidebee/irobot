//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "actor.hpp"
#include "util/lock.hpp"

namespace irobot {

    bool Actor::Init() {

        if (!(this->mutex = SDL_CreateMutex())) {
            return false;
        }
        if (!(this->thread_cond = SDL_CreateCond())) {
            SDL_DestroyMutex(this->mutex);
            return false;
        }
        this->stopped = false;
        this->thread= nullptr;
        return true;
    }


    void Actor::Destroy() {
        SDL_DestroyCond(this->thread_cond);
        SDL_DestroyMutex(this->mutex);

    }

    void Actor::Stop() {
        util::mutex_lock(this->mutex);
        this->stopped = true;
        util::cond_signal(this->thread_cond);
        util::mutex_unlock(this->mutex);
    }

    void Actor::Join() {
        SDL_WaitThread(this->thread, nullptr);

    }
}