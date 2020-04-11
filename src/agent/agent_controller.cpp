//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_controller.hpp"
#include "util/log.hpp"
#include "util/lock.hpp"

namespace irobot::agent {
    bool AgentController::Init(socket_t server_socket, message::MessageHandler handler) {
        bool initialized = Actor::Init();
        if (!initialized) {
            return false;
        }
        this->control_server_socket = server_socket;
        this->message_handler = handler;
        return true;
    }

    bool AgentController::WaitForClientConnection() {
        if (this->control_socket != INVALID_SOCKET) {
            platform::close_socket(&this->control_socket);
        }
        this->control_socket = platform::net_accept(this->control_server_socket);
        LOGD("Agent controller client connected");
        return this->control_socket != INVALID_SOCKET;
    }

    void AgentController::ProcessMessage(struct message::ControlMessage *msg) {
        if (this->message_handler) {
            this->message_handler(msg);
        }
    }

    bool AgentController::SendMessage(
            message::ControlMessage *msg) {
        if (this->control_socket != INVALID_SOCKET) {
            auto json_str = msg->JsonSerialize();
            int length = json_str.size();
            char cstr[length + 1];
            strcpy(cstr, json_str.c_str());

            if (!length) {
                return false;
            }
            int w = platform::net_send_all(this->control_socket,
                                           cstr, length);
            return w == length;
        }
        return true;
    }


    bool AgentController::Start() {

        LOGD("Starting agent controller thread");
        this->thread = SDL_CreateThread(RunAgentController,
                                        "agent controller", this);
        if (!this->thread) {
            LOGC("Could not start agent controller thread");
            return false;
        }

        LOGD("Starting agent recorder thread");
        this->record_thread = SDL_CreateThread(RunAgentRecorder, "agent recorder",
                                               this);
        if (!this->record_thread) {
            LOGC("Could not start agent recorder thread");
            return false;
        }

        return true;
    }

    void AgentController::Destroy() {
        Actor::Destroy();
        message::ControlMessage msg{};
        while (cbuf_take(&this->queue, &msg)) {
            msg.Destroy();
        }
        LOGD("Agent controller stopped");

    }


    void AgentController::Join() {
        if (this->control_socket != INVALID_SOCKET) {
            SDL_WaitThread(this->thread, nullptr);
            SDL_WaitThread(this->record_thread, nullptr);
        }

    }

    ssize_t AgentController::ProcessMessages(const unsigned char *buf, size_t len) {
        size_t head = 0;
        for (;;) {
            message::ControlMessage msg{};
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

    int AgentController::RunAgentRecorder(void *data) {
        auto *controller = static_cast<AgentController *>(data);
        for (;;) {
            util::mutex_lock(controller->mutex);
            while (!controller->stopped && cbuf_is_empty(&controller->queue)) {
                util::cond_wait(controller->thread_cond, controller->mutex);
            }
            if (controller->stopped) {
                // stop immediately, do not process further msgs
                util::mutex_unlock(controller->mutex);
                break;
            }
            message::ControlMessage msg{};
            bool non_empty = cbuf_take(&controller->queue, &msg);
            assert(non_empty);
            (void) non_empty;
            util::mutex_unlock(controller->mutex);
            bool ok = controller->SendMessage(&msg);
            msg.Destroy();
            if (!ok) {
                LOGD("Could not write msg to socket");
                break;
            }
        }
        return 0;
    }

    int AgentController::RunAgentController(void *data) {
        auto *controller = (AgentController *) data;
        if (!controller->WaitForClientConnection()) {
            return 0;
        }
        unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE * 2];
        size_t head = 0;
        while (!controller->stopped) {
            assert(head < CONTROL_MSG_SERIALIZED_MAX_SIZE * 2);
            ssize_t r = platform::net_recv(controller->control_socket, buf,
                                           CONTROL_MSG_SERIALIZED_MAX_SIZE * 2 - head);
            if (r <= 0) {
                LOGD("Control socket error ,trying to re-establish connection");
                if (!controller->WaitForClientConnection()) {
                    LOGD("Failed to re-establish connection");
                    break;
                }

            }
            ssize_t consumed = controller->ProcessMessages(buf, r);
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