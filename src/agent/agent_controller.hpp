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
        socket_t control_socket = INVALID_SOCKET;
        socket_t control_server_socket = INVALID_SOCKET;
        message::ControlMessageQueue queue{};
        SDL_Thread *record_thread = nullptr;
        message::MessageHandler message_handler = nullptr;
        void * entity = nullptr;

        void Destroy() override;

        bool Init(socket_t server_socket, message::MessageHandler message_handler,void * entity);

        bool WaitForClientConnection();

        bool Start() override;

        void Join() override;

        static int RunAgentController(void *data);

        static int RunAgentRecorder(void *data);

    private:
        bool SendMessage(message::ControlMessage *msg);

        ssize_t ProcessMessages(const unsigned char *buf, size_t len);

        void ProcessMessage(message::ControlMessage *msg);

    };

}

#endif //ANDROID_IROBOT_AGENT_CONTROLLER_HPP
