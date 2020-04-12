//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_STREAM_HPP
#define ANDROID_IROBOT_AGENT_STREAM_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_timer.h>

#if defined (__cplusplus)
}
#endif


#include "core/actor.hpp"
#include "util/cbuf.hpp"
#include "platform/net.hpp"
#include "message/blob_msg.hpp"

namespace irobot::agent {

    class AgentStream : public Actor {
    public:
        socket_t video_socket = INVALID_SOCKET;
        socket_t video_server_socket = INVALID_SOCKET;
        SDL_Thread *receiver_thread = nullptr;
        message::BlobMessageQueue queue{};

        bool Init(socket_t server_socket);

        bool WaitForClientConnection();

        void Destroy() override;

        void Join() override;

        bool Start() override;

        bool PushMessage(const message::BlobMessage *msg);

        bool ProcessMessage(message::BlobMessage *msg);

        static int RunStream(void *data);

        static int RunAgentReceiver(void *data);

        bool IsConnected();

        float GetTransferSpeed();


    private:

        int buffer_index = 0;
        unsigned long  total_bytes =0;
        unsigned long total_frame =0;
        Uint32 start_ticks =0;
        Uint32 last_ticks =0;


    };

}

#endif //ANDROID_IROBOT_AGENT_STREAM_HPP
