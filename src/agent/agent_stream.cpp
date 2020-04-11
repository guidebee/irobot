//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_stream.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

namespace irobot::agent {

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


    void AgentStream::Destroy() {
        Actor::Destroy();
        message::BlobMessage msg{};
        while (cbuf_take(&this->queue, &msg)) {
            msg.Destroy();
        }
        LOGD("Agent stream stopped");

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
        unsigned char serialized_msg[BLOB_MSG_SERIALIZED_MAX_SIZE];
        int length = msg->Serialize(serialized_msg);
        if (!length) {
            return false;
        }
        int w = platform::net_send_all(this->video_socket,
                                       serialized_msg, length);
        return w == length;
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
            util::mutex_unlock(stream->mutex);
            bool ok = stream->ProcessMessage(&msg);
            msg.Destroy();
            if (!ok) {
                LOGD("Could not write msg to socket");
                break;
            }
        }
        return 0;
    }

    bool AgentStream::Start() {
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