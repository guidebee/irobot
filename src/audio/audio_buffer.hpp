//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AUDIO_BUFFER_HPP
#define ANDROID_IROBOT_AUDIO_BUFFER_HPP

#include <SDL2/SDL_mutex.h>

#include <cstdint>
#include <vector>

namespace irobot::audio {

    // thread-safe ring buffer of raw interleaved PCM bytes, shared between
    // the decoder thread (producer) and the SDL audio callback (consumer)
    class AudioBuffer {

    public:
        bool Init(size_t capacity);

        void Destroy();

        // append data to the buffer; if there is not enough room, the
        // oldest bytes are dropped to make space (matches the underlying
        // real-time audio stream: latency must be bounded)
        void Write(const uint8_t *src, size_t len);

        // fill out with len bytes; any missing bytes (buffer underrun) are
        // filled with silence
        void Read(uint8_t *dst, size_t len, uint8_t silence);

    private:
        std::vector<uint8_t> data;
        size_t capacity = 0;
        size_t head = 0; // next write position
        size_t available = 0; // bytes ready to read
        SDL_mutex *mutex = nullptr;
    };
}

#endif //ANDROID_IROBOT_AUDIO_BUFFER_HPP
