//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AUDIO_STREAM_HPP
#define ANDROID_IROBOT_AUDIO_STREAM_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <libavformat/avformat.h>

#if defined (__cplusplus)
}
#endif

#include "core/actor.hpp"
#include "platform/net.hpp"

namespace irobot::audio {

    class AudioDecoder;

    class AudioStream : public Actor {

    public:
        socket_t audio_socket = 0;
        AudioDecoder *decoder = nullptr;

        void Init(socket_t socket, AudioDecoder *pDecoder);

        bool Start() override;

        void Stop() override;

        static int RunStream(void *data);

    private:
        bool ReceiveCodecId(uint32_t *codec_id);

        bool ReceivePacket(AVPacket *packet);
    };
}

#endif //ANDROID_IROBOT_AUDIO_STREAM_HPP
