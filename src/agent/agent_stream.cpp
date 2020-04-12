//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_stream.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

namespace irobot::agent {

    unsigned char data_buffer[2][BLOB_MSG_SERIALIZED_MAX_SIZE];

    bool AgentStream::Init(socket_t socket) {
        cbuf_init(&this->queue);
        bool initialized = Actor::Init();
        if (!initialized) {

            return false;
        }
        this->video_server_socket = socket;
        this->stopped = false;
        return true;
    }


    bool AgentStream::WaitForClientConnection() {
        if (this->video_socket != INVALID_SOCKET) {
            platform::close_socket(&this->video_socket);
        }
        this->video_socket = platform::net_accept(this->video_server_socket);
        LOGI("Agent stream client connected");
        return this->video_socket != INVALID_SOCKET;
    }

    void AgentStream::Destroy() {
        Actor::Destroy();
        message::BlobMessage msg{};
        while (cbuf_take(&this->queue, &msg)) {
            msg.Destroy();
        }
        LOGI("Agent stream stopped");

    }

    bool AgentStream::PushMessage(
            const message::BlobMessage *msg) {
        util::mutex_lock(this->mutex);
        bool was_empty = cbuf_is_empty(&this->queue);
        bool res = cbuf_push(&this->queue, *msg);
        if (was_empty) {
            util::cond_signal(this->thread_cond);
        }
        util::mutex_unlock(this->mutex);
        return res;
    }

    bool AgentStream::ProcessMessage(
            message::BlobMessage *msg) {
        if (this->video_socket != INVALID_SOCKET) {

            int length = msg->Serialize(data_buffer[buffer_index % 2]);
            if (!length) {
                return false;
            }
            int w = platform::net_send_all(this->video_socket,
                                           data_buffer[buffer_index % 2], length);

            buffer_index += 1;
            return w == length;
        }
        return true;
    }

    bool AgentStream::IsConnected() {
        if (this->video_socket != INVALID_SOCKET) {
            bool connected = platform::net_try_recv(this->video_socket);
            return connected;
        }
        return false;
    }


    int AgentStream::RunAgentReceiver(void *data) {
        auto *controller = (AgentStream *) data;
        if (!controller->WaitForClientConnection()) {
            return 0;
        }

        while (!controller->stopped) {
            bool connected = controller->IsConnected();
            if (!connected) {
                LOGI("Control socket error ,trying to re-establish connection");
                if (!controller->WaitForClientConnection()) {
                    LOGD("Failed to re-establish connection");
                    break;
                }
            }
            SDL_Delay(1);


        }
        return 0;
    }

    int AgentStream::RunStream(void *data) {
        auto *stream = static_cast<AgentStream *>(data);

        for (;;) {

            util::mutex_lock(stream->mutex);
            while (!stream->stopped && cbuf_is_empty(&stream->queue)) {
                util::cond_wait(stream->thread_cond, stream->mutex);
            }
            if (stream->stopped) {
                // stop immediately, do not process further msgs
                util::mutex_unlock(stream->mutex);
                break;
            }
            message::BlobMessage msg{};
            bool non_empty = cbuf_take(&stream->queue, &msg);
            assert(non_empty);
            (void) non_empty;
            bool ok = stream->ProcessMessage(&msg);
            msg.Destroy();
            util::mutex_unlock(stream->mutex);

            if (!ok) {
                LOGD("stream socket error 2,trying to re-establish connection");


            }
        }
        return 0;
    }

    void AgentStream::Join() {
        SDL_WaitThread(this->thread, nullptr);
        SDL_WaitThread(this->receiver_thread, nullptr);

    }

    bool AgentStream::Start() {

        LOGI("Starting agent receiver thread");
        this->receiver_thread = SDL_CreateThread(RunAgentReceiver, "agent receiver",
                                                 this);
        if (!this->receiver_thread) {
            LOGC("Could not start agent receiver thread");
            return false;
        }

        LOGD("Starting agent stream thread");
        this->thread = SDL_CreateThread(RunStream, "agent stream",
                                        this);
        if (!this->thread) {
            LOGC("Could not start agent stream thread");
            return false;
        }


        return true;
    }


}