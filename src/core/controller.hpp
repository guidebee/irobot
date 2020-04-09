//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CONTROLLER_HPP
#define ANDROID_IROBOT_CONTROLLER_HPP


#include "actor.hpp"
#include "android/receiver.hpp"
#include "message/control_msg.hpp"
#include "util/cbuf.hpp"
#include "platform/net.hpp"

namespace irobot {

    struct ControlMessageQueue CBUF(message::ControlMessage, 64);

    class Controller : public Actor {

    public:
        socket_t control_socket = 0;
        ControlMessageQueue queue{};
        android::Receiver receiver{};

        bool Init(socket_t control_socket);

        void Destroy() override;

        void Stop() override;

        bool Start() override;

        void Join() override;

        bool PushMessage(const message::ControlMessage *msg);

        static int RunController(void *data);

    private:

        bool ProcessMessage(message::ControlMessage *msg);

    };
}

#endif //ANDROID_IROBOT_CONTROLLER_HPP
