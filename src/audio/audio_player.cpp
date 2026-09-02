//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#include "audio_player.hpp"

#include "audio_buffer.hpp"
#include "util/log.hpp"

namespace irobot::audio
{
    void AudioPlayer::Init(AudioBuffer* buf)
    {
        this->audio_buffer = buf;
        this->device = 0;
    }

    void SDLCALL AudioPlayer::AudioCallback(void* userdata, uint8_t* stream, int len)
    {
        auto* player = (AudioPlayer*)userdata;
        player->audio_buffer->Read(stream, (size_t)len, player->silence);
    }

    bool AudioPlayer::Open(int sample_rate, int channels)
    {
        SDL_AudioSpec desired;
        SDL_zero(desired);
        desired.freq = sample_rate;
        desired.format = AUDIO_S16SYS;
        desired.channels = (Uint8)channels;
        // ~21ms at 48kHz: low enough latency, large enough to avoid glitches
        desired.samples = 1024;
        desired.callback = AudioCallback;
        desired.userdata = this;

        SDL_AudioSpec obtained;
        // request the exact format: the buffer is already filled with S16
        // samples at this rate/channel count, so SDL must not silently
        // substitute a different one
        this->device = SDL_OpenAudioDevice(nullptr, 0, &desired, &obtained, 0);
        if (!this->device)
        {
            LOGE("Could not open audio device: %s", SDL_GetError());
            return false;
        }

        this->silence = obtained.silence;

        SDL_PauseAudioDevice(this->device, 0);
        return true;
    }

    void AudioPlayer::Close()
    {
        if (this->device)
        {
            SDL_CloseAudioDevice(this->device);
            this->device = 0;
        }
    }
}
