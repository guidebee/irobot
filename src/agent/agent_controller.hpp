//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_CONTROLLER_HPP
#define ANDROID_IROBOT_AGENT_CONTROLLER_HPP

#include "core/actor.hpp"
#include "util/cbuf.hpp"
#include "platform/net.hpp"
#include "message/control_msg.hpp"

namespace irobot::agent {

    class AgentController : public Actor {
    public:
        socket_t control_socket = 0;

        bool Init(socket_t socket);

        bool Start() override;

        static void ProcessMessage(struct message::ControlMessage *msg);

        static ssize_t ProcessMessages(const unsigned char *buf, size_t len);

        static int RunAgentController(void *data);

    };

}

#endif //ANDROID_IROBOT_AGENT_CONTROLLER_HPP
