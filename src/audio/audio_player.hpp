//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AUDIO_PLAYER_HPP
#define ANDROID_IROBOT_AUDIO_PLAYER_HPP

#include <SDL2/SDL_audio.h>

#include <cstdint>

namespace irobot::audio {

    class AudioBuffer;

    class AudioPlayer {

    public:
        AudioBuffer *audio_buffer = nullptr;
        SDL_AudioDeviceID device = 0;
        uint8_t silence = 0;

        void Init(AudioBuffer *buf);

        bool Open(int sample_rate, int channels);

        void Close();

    private:
        static void SDLCALL AudioCallback(void *userdata, uint8_t *stream, int len);
    };
}

#endif //ANDROID_IROBOT_AUDIO_PLAYER_HPP
