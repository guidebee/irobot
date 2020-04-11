//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_STREAM_HPP
#define ANDROID_IROBOT_AGENT_STREAM_HPP

#include "core/actor.hpp"
#include "util/cbuf.hpp"
#include "platform/net.hpp"
#include "message/blob_msg.hpp"

namespace irobot::agent {

    class AgentStream : public Actor {
    public:
        socket_t video_socket = INVALID_SOCKET;
        socket_t video_server_socket = INVALID_SOCKET;
        message::BlobMessageQueue queue{};

        bool Init(socket_t server_socket);

        bool WaitForClientConnection();

        void Destroy() override;

        bool Start() override;

        bool PushMessage(const message::BlobMessage *msg);

        bool ProcessMessage(message::BlobMessage *msg);

        static int RunStream(void *data);

    private:


    };

}

#endif //ANDROID_IROBOT_AGENT_STREAM_HPP
