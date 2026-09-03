//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_controller.hpp"
#include "util/log.hpp"
#include "util/lock.hpp"
#include "util/buffer_util.hpp"

#include <cstring>
#include <vector>

namespace irobot::agent
{
    bool AgentController::Init(socket_t server_socket, message::MessageHandler handler, void* pEntity)
    {
        bool initialized = Actor::Init();
        if (!initialized)
        {
            return false;
        }
        this->control_server_socket = server_socket;
        this->message_handler = handler;
        this->entity = pEntity;
        return true;
    }

    bool AgentController::WaitForClientConnection()
    {
        if (this->control_socket != INVALID_SOCKET)
        {
            platform::close_socket(&this->control_socket);
        }
        this->control_socket = platform::net_accept(this->control_server_socket);
        LOGI("Agent controller client connected");
        return this->control_socket != INVALID_SOCKET;
    }

    void AgentController::ProcessMessage(struct message::ControlMessage* msg)
    {
        if (this->message_handler)
        {
            this->message_handler(this->entity, msg);
        }
    }

    // wire framing for the JSON control channel: [4-byte BE length][JSON payload].
    // Without this, two messages written back-to-back can coalesce into a single
    // recv() on the reader side and fail to parse as one JSON document -- see
    // ProcessMessages() below and docs/opengym_implementation_plan.md §3.1/§4.1.
    static constexpr size_t kFrameHeaderSize = 4;

    bool AgentController::SendMessage(
        message::ControlMessage* msg)
    {
        if (this->control_socket != INVALID_SOCKET)
        {
            auto json_str = msg->JsonSerialize();
            uint32_t length = (uint32_t)json_str.size();
            if (!length)
            {
                return false;
            }
            std::vector<unsigned char> frame(kFrameHeaderSize + length);
            util::buffer_write32be(frame.data(), length);
            memcpy(frame.data() + kFrameHeaderSize, json_str.data(), length);
            int w = platform::net_send_all(this->control_socket,
                                           frame.data(), frame.size());
            return w == (int)frame.size();
        }
        return true;
    }


    bool AgentController::Start()
    {
        LOGI("Starting agent controller thread");
        this->thread = SDL_CreateThread(RunAgentController,
                                        "agent controller", this);
        if (!this->thread)
        {
            LOGC("Could not start agent controller thread");
            return false;
        }

        LOGD("Starting agent recorder thread");
        this->record_thread = SDL_CreateThread(RunAgentRecorder, "agent recorder",
                                               this);
        if (!this->record_thread)
        {
            LOGC("Could not start agent recorder thread");
            return false;
        }

        return true;
    }

    void AgentController::Destroy()
    {
        Actor::Destroy();
        message::ControlMessage msg{};
        while (cbuf_take(&this->queue, &msg))
        {
            msg.Destroy();
        }
        LOGI("Agent controller stopped");
    }


    void AgentController::Join()
    {
        if (this->control_socket != INVALID_SOCKET)
        {
            SDL_WaitThread(this->thread, nullptr);
            SDL_WaitThread(this->record_thread, nullptr);
        }
    }

    ssize_t AgentController::ProcessMessages(const unsigned char* buf, size_t len)
    {
        // max payload a well-formed frame can declare -- anything bigger than the
        // read buffer itself can never be fully received, so it means a corrupt
        // stream (or a pre-framing client) rather than "wait for more bytes".
        constexpr size_t kMaxPayload = CONTROL_MSG_SERIALIZED_MAX_SIZE * 2 - kFrameHeaderSize;

        size_t head = 0;
        for (;;)
        {
            if (len - head < kFrameHeaderSize)
            {
                return head;
            }
            uint32_t payload_len = util::buffer_read32be(&buf[head]);
            if (payload_len > kMaxPayload)
            {
                LOGW("Control message frame too large (%u bytes), dropping connection", payload_len);
                return -1;
            }
            if (len - head < kFrameHeaderSize + payload_len)
            {
                return head;
            }
            message::ControlMessage msg{};
            size_t r = msg.JsonDeserialize(&buf[head + kFrameHeaderSize], payload_len);
            if (r > 0)
            {
                ProcessMessage(&msg);
            }
            msg.Destroy();
            head += kFrameHeaderSize + payload_len;
            assert(head <= len);
            if (head == len)
            {
                return head;
            }
        }
    }

    int AgentController::RunAgentRecorder(void* data)
    {
        auto* controller = static_cast<AgentController*>(data);
        for (;;)
        {
            util::mutex_lock(controller->mutex);
            while (!controller->stopped && cbuf_is_empty(&controller->queue))
            {
                util::cond_wait(controller->thread_cond, controller->mutex);
            }
            if (controller->stopped)
            {
                // stop immediately, do not process further msgs
                util::mutex_unlock(controller->mutex);
                break;
            }
            message::ControlMessage msg{};
            bool non_empty = cbuf_take(&controller->queue, &msg);
            assert(non_empty);
            (void)non_empty;
            util::mutex_unlock(controller->mutex);
            bool ok = controller->SendMessage(&msg);
            msg.Destroy();
            if (!ok)
            {
                LOGD("Could not write msg to socket");
                break;
            }
        }
        return 0;
    }

    int AgentController::RunAgentController(void* data)
    {
        auto* controller = (AgentController*)data;
        if (!controller->WaitForClientConnection())
        {
            return 0;
        }
        constexpr size_t kBufSize = CONTROL_MSG_SERIALIZED_MAX_SIZE * 2;
        unsigned char buf[kBufSize];
        size_t head = 0;
        while (!controller->stopped)
        {
            assert(head < kBufSize);
            // append new bytes after whatever partial frame is already buffered --
            // recv()'ing into buf[0] here would clobber it instead
            ssize_t r = platform::net_recv(controller->control_socket, buf + head,
                                           kBufSize - head);
            if (r <= 0)
            {
                LOGI("Control socket error ,trying to re-establish connection");
                if (!controller->WaitForClientConnection())
                {
                    LOGD("Failed to re-establish connection");
                    break;
                }
                // the old connection's buffered partial frame (if any) is
                // meaningless on a fresh connection
                head = 0;
                continue;
            }
            size_t total = head + r;
            ssize_t consumed = controller->ProcessMessages(buf, total);
            if (consumed == -1)
            {
                // an error occurred
                break;
            }
            if (consumed > 0 && (size_t)consumed < total)
            {
                // shift the remaining data in the buffer
                memmove(buf, &buf[consumed], total - consumed);
            }
            head = total - consumed;
        }
        return 0;
    }
}