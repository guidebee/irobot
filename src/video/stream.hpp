//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_STREAM_HPP
#define ANDROID_IROBOT_STREAM_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <unistd.h>
#include <libavformat/avformat.h>
#include <SDL2/SDL_events.h>
#include <SDL2/SDL_thread.h>
#include <SDL2/SDL_atomic.h>

#if defined (__cplusplus)
}
#endif

#include <cassert>
#include <cstdint>

#include "config.hpp"
#include "core/actor.hpp"
#include "platform/net.hpp"
#include "video/decoder.hpp"

namespace irobot::video {

    class VideoStream : public Actor {

    public:
        socket_t video_socket = 0;
        struct Decoder *decoder = nullptr;
        struct Recorder *recorder = nullptr;
        AVCodecContext *codec_ctx = nullptr;
        AVCodecParserContext *parser = nullptr;
        // successive packets may need to be concatenated, until a non-config
        // packet is available
        bool has_pending = false;
        AVPacket pending{};

        void Init(socket_t socket,
                  struct Decoder *pDecoder, Recorder *pRecorder);

        bool Start() override;

        void Stop() override;

        bool ReceivePacket(AVPacket *packet);

        bool PushPacket(AVPacket *packet);

        static void NotifyStopped();

        static int RunStream(void *data);

    private:

        bool ProcessConfigPacket(AVPacket *packet);

        bool ProcessFrame(AVPacket *packet);

        bool Parse(AVPacket *packet);

    };

}

#endif //ANDROID_IROBOT_STREAM_HPP
