//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#include "audio_buffer.hpp"

#include <cstring>

#include "core/common.hpp"
#include "util/lock.hpp"

namespace irobot::audio
{
    bool AudioBuffer::Init(size_t cap)
    {
        this->data.resize(cap);
        this->capacity = cap;
        this->head = 0;
        this->available = 0;
        this->mutex = SDL_CreateMutex();
        return this->mutex != nullptr;
    }

    void AudioBuffer::Destroy()
    {
        SDL_DestroyMutex(this->mutex);
        this->mutex = nullptr;
    }

    void AudioBuffer::Write(const uint8_t* src, size_t len)
    {
        util::mutex_lock(this->mutex);

        if (len >= this->capacity)
        {
            // keep only the tail; the rest would be dropped anyway
            src += len - this->capacity;
            len = this->capacity;
            this->head = 0;
            this->available = 0;
        }

        size_t first_chunk = MIN(len, this->capacity - this->head);
        memcpy(&this->data[this->head], src, first_chunk);
        if (len > first_chunk)
        {
            memcpy(&this->data[0], src + first_chunk, len - first_chunk);
        }
        this->head = (this->head + len) % this->capacity;

        this->available += len;
        if (this->available > this->capacity)
        {
            // buffer overflow: the oldest samples were just overwritten in
            // place, simply shrink the readable window to match
            this->available = this->capacity;
        }

        util::mutex_unlock(this->mutex);
    }

    void AudioBuffer::Read(uint8_t* dst, size_t len, uint8_t silence)
    {
        util::mutex_lock(this->mutex);

        size_t to_read = MIN(len, this->available);
        size_t tail = (this->head + this->capacity - this->available) % this->capacity;

        size_t first_chunk = MIN(to_read, this->capacity - tail);
        memcpy(dst, &this->data[tail], first_chunk);
        if (to_read > first_chunk)
        {
            memcpy(dst + first_chunk, &this->data[0], to_read - first_chunk);
        }

        this->available -= to_read;

        util::mutex_unlock(this->mutex);

        if (to_read < len)
        {
            memset(dst + to_read, silence, len - to_read);
        }
    }
}
