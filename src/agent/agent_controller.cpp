//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_controller.hpp"
#include "util/log.hpp"

namespace irobot::agent {
    bool AgentController::Init(socket_t socket) {
        bool initialized = Actor::Init();
        if (!initialized) {
            return false;
        }
        this->control_socket = socket;
        return true;
    }

    void AgentController::ProcessMessage(struct message::ControlMessage *msg) {
        switch (msg->type) {
            default:
                break;
        }
    }

    bool AgentController::Start() {

        LOGD("Starting agent controller thread");
        this->thread = SDL_CreateThread(AgentController::RunAgentController,
                                        "agent controller", this);
        if (!this->thread) {
            LOGC("Could not start agent controller thread");
            return false;
        }
        return true;
    }

    ssize_t AgentController::ProcessMessages(const unsigned char *buf, size_t len) {
        size_t head = 0;
        for (;;) {
            struct message::ControlMessage msg{};

            ssize_t r = msg.JsonDeserialize(&buf[head], len - head);
            if (r == -1) {
                return -1;
            }
            if (r == 0) {
                return head;
            }

            ProcessMessage(&msg);
            msg.Destroy();

            head += r;
            assert(head <= len);
            if (head == len) {
                return head;
            }
        }
    }

    int AgentController::RunAgentController(void *data) {
        auto *receiver = (AgentController *) data;
        unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE * 2];
        size_t head = 0;

        while (!receiver->stopped) {
            assert(head < CONTROL_MSG_SERIALIZED_MAX_SIZE * 2);
            ssize_t r = platform::net_recv(receiver->control_socket, buf,
                                           CONTROL_MSG_SERIALIZED_MAX_SIZE * 2 - head);
            if (r <= 0) {
                LOGD("AgentController stopped");
                break;
            }

            ssize_t consumed = ProcessMessages(buf, r);
            if (consumed == -1) {
                // an error occurred
                break;
            }

            if (consumed) {
                // shift the remaining data in the buffer
                memmove(buf, &buf[consumed], r - consumed);
                head = r - consumed;
            }
        }

        return 0;
    }


}