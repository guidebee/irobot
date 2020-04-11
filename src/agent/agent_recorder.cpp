//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_recorder.hpp"

#include <cassert>

#include "util/lock.hpp"
#include "util/log.hpp"

namespace irobot::agent {

    bool AgentRecorder::Init(socket_t socket) {
        cbuf_init(&this->queue);
        bool initialized = Actor::Init();
        if (!initialized) {

            return false;
        }
        this->control_socket = socket;
        this->stopped = false;
        return true;
    }


    void AgentRecorder::Destroy() {
        Actor::Destroy();
        message::ControlMessage msg{};
        while (cbuf_take(&this->queue, &msg)) {
            msg.Destroy();
        }

    }

    bool AgentRecorder::PushMessage(
            const message::ControlMessage *msg) {
        util::mutex_lock(this->mutex);
        bool was_empty = cbuf_is_empty(&this->queue);
        bool res = cbuf_push(&this->queue, *msg);
        if (was_empty) {
            util::cond_signal(this->thread_cond);
        }
        util::mutex_unlock(this->mutex);
        return res;
    }

    bool AgentRecorder::ProcessMessage(
            message::ControlMessage *msg) {
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

    int AgentRecorder::RunRecorder(void *data) {
        auto *recorder = static_cast<AgentRecorder *>(data);
        for (;;) {
            util::mutex_lock(recorder->mutex);
            while (!recorder->stopped && cbuf_is_empty(&recorder->queue)) {
                util::cond_wait(recorder->thread_cond, recorder->mutex);
            }
            if (recorder->stopped) {
                // stop immediately, do not process further msgs
                util::mutex_unlock(recorder->mutex);
                break;
            }
            message::ControlMessage msg{};
            bool non_empty = cbuf_take(&recorder->queue, &msg);
            assert(non_empty);
            (void) non_empty;
            util::mutex_unlock(recorder->mutex);
            bool ok = recorder->ProcessMessage(&msg);
            msg.Destroy();
            if (!ok) {
                LOGD("Could not write msg to socket");
                break;
            }
        }
        return 0;
    }

    bool AgentRecorder::Start() {
        LOGD("Starting agent recorder thread");
        this->thread = SDL_CreateThread(RunRecorder, "agent recorder",
                                        this);
        if (!this->thread) {
            LOGC("Could not start agent recorder thread");
            return false;
        }

        return true;
    }


}