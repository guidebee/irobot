//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_RECORDER_HPP
#define ANDROID_IROBOT_AGENT_RECORDER_HPP

#include "core/actor.hpp"
#include "util/cbuf.hpp"
#include "platform/net.hpp"
#include "message/control_msg.hpp"

namespace irobot::agent {

    class AgentRecorder : public Actor {
    public:
        socket_t control_socket = 0;
        message::ControlMessageQueue queue{};

        bool Init(socket_t socket);

        void Destroy() override;

        bool Start() override;

        bool PushMessage(const message::ControlMessage *msg);

        static int RunController(void *data);

    private:

        bool ProcessMessage(message::ControlMessage *msg);

    };

}

#endif //ANDROID_IROBOT_AGENT_RECORDER_HPP
