//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_controller.hpp"
#include "util/log.hpp"
#include "util/lock.hpp"
#include "util/buffer_util.hpp"

#include <algorithm>
#include <cstring>
#include <vector>

namespace irobot::agent
{
    // wire framing for the JSON control channel: [4-byte BE length][JSON payload].
    // Without this, two messages written back-to-back can coalesce into a single
    // recv() on the reader side and fail to parse as one JSON document -- see
    // ProcessMessages() below and docs/opengym_implementation_plan.md §3.1/§4.1.
    static constexpr size_t kFrameHeaderSize = 4;

    bool AgentController::Init(socket_t server_socket, message::MessageHandler handler, void* pEntity)
    {
        bool initialized = Actor::Init();
        if (!initialized)
        {
            return false;
        }
        this->sessions_mutex = SDL_CreateMutex();
        if (!this->sessions_mutex)
        {
            return false;
        }
        this->control_server_socket = server_socket;
        this->message_handler = handler;
        this->entity = pEntity;
        return true;
    }

    void AgentController::AddSession(ControlSession* session)
    {
        util::mutex_lock(this->sessions_mutex);
        this->sessions.push_back(session);
        util::mutex_unlock(this->sessions_mutex);
    }

    bool AgentController::RemoveSessionIfNotStopping(ControlSession* session)
    {
        util::mutex_lock(this->sessions_mutex);
        bool owner_self = !this->stopping;
        if (owner_self)
        {
            auto it = std::find(this->sessions.begin(), this->sessions.end(), session);
            if (it != this->sessions.end())
            {
                this->sessions.erase(it);
            }
        }
        util::mutex_unlock(this->sessions_mutex);
        return owner_self;
    }

    void AgentController::ProcessMessage(struct message::ControlMessage* msg)
    {
        if (this->message_handler)
        {
            this->message_handler(this->entity, msg);
        }
    }

    bool AgentController::BuildFrame(const message::ControlMessage* msg, std::vector<unsigned char>& out)
    {
        auto json_str = ((message::ControlMessage*)msg)->JsonSerialize();
        uint32_t length = (uint32_t)json_str.size();
        if (!length)
        {
            return false;
        }
        out.resize(kFrameHeaderSize + length);
        util::buffer_write32be(out.data(), length);
        memcpy(out.data() + kFrameHeaderSize, json_str.data(), length);
        return true;
    }

    bool AgentController::PushMessage(const message::ControlMessage* msg)
    {
        ControlFrame frame;
        if (!BuildFrame(msg, frame.bytes))
        {
            return false;
        }

        util::mutex_lock(this->sessions_mutex);
        std::vector<ControlSession*> snapshot = this->sessions;
        util::mutex_unlock(this->sessions_mutex);

        for (ControlSession* session : snapshot)
        {
            util::mutex_lock(session->mutex);
            if (session->alive)
            {
                bool was_full = cbuf_is_full(&session->queue);
                if (!was_full)
                {
                    bool was_empty = cbuf_is_empty(&session->queue);
                    cbuf_push(&session->queue, frame);
                    if (was_empty)
                    {
                        util::cond_signal(session->cond);
                    }
                }
                else
                {
                    LOGD("Control client #%d queue is full, dropping message", session->id);
                }
            }
            util::mutex_unlock(session->mutex);
        }
        return true;
    }

    bool AgentController::Start()
    {
        LOGI("Starting agent controller acceptor thread");
        this->thread = SDL_CreateThread(RunAcceptor, "agent ctrl acceptor", this);
        if (!this->thread)
        {
            LOGC("Could not start agent controller acceptor thread");
            return false;
        }
        return true;
    }

    void AgentController::Stop()
    {
        this->stopped = true;
        util::mutex_lock(this->sessions_mutex);
        this->stopping = true;
        std::vector<ControlSession*> snapshot = std::move(this->sessions);
        this->sessions.clear();
        util::mutex_unlock(this->sessions_mutex);

        // closesocket() -- not shutdown() -- is what reliably aborts another
        // thread's blocking recv()/send() on this socket (shutdown() alone
        // was observed not to unblock a concurrently-blocked recv() here).
        // Close every session's socket up front so the reader/writer threads
        // exit promptly, then join+free once nothing can still be using them.
        for (ControlSession* session : snapshot)
        {
            util::mutex_lock(session->mutex);
            session->alive = false;
            util::cond_signal(session->cond);
            util::mutex_unlock(session->mutex);
            platform::close_socket(&session->socket);
        }

        for (ControlSession* session : snapshot)
        {
            SDL_WaitThread(session->reader_thread, nullptr);
            SDL_WaitThread(session->writer_thread, nullptr);
            SDL_DestroyMutex(session->mutex);
            SDL_DestroyCond(session->cond);
            delete session;
        }
    }

    void AgentController::Destroy()
    {
        Actor::Destroy();
        SDL_DestroyMutex(this->sessions_mutex);
        LOGI("Agent controller stopped");
    }

    void AgentController::Join()
    {
        SDL_WaitThread(this->thread, nullptr);
    }

    ssize_t AgentController::ProcessMessages(ControlSession* session, size_t len)
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
            uint32_t payload_len = util::buffer_read32be(&session->buf[head]);
            if (payload_len > kMaxPayload)
            {
                LOGW("Control client #%d: frame too large (%u bytes), dropping connection",
                     session->id, payload_len);
                return -1;
            }
            if (len - head < kFrameHeaderSize + payload_len)
            {
                return head;
            }
            message::ControlMessage msg{};
            size_t r = msg.JsonDeserialize(&session->buf[head + kFrameHeaderSize], payload_len);
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

    int AgentController::RunSessionWriter(void* data)
    {
        auto* session = static_cast<ControlSession*>(data);
        for (;;)
        {
            util::mutex_lock(session->mutex);
            while (session->alive && cbuf_is_empty(&session->queue))
            {
                util::cond_wait(session->cond, session->mutex);
            }
            if (!session->alive)
            {
                util::mutex_unlock(session->mutex);
                break;
            }
            ControlFrame frame{};
            bool non_empty = cbuf_take(&session->queue, &frame);
            assert(non_empty);
            (void)non_empty;
            util::mutex_unlock(session->mutex);

            int w = platform::net_send_all(session->socket, frame.bytes.data(), frame.bytes.size());
            bool ok = w == (int)frame.bytes.size();
            if (!ok)
            {
                LOGD("Control client #%d: write error", session->id);
                util::mutex_lock(session->mutex);
                session->alive = false;
                util::mutex_unlock(session->mutex);
                // unblock the reader's recv() promptly rather than waiting for
                // Stop() or the peer to notice
                platform::net_shutdown(session->socket, SHUT_RDWR);
                break;
            }
        }
        return 0;
    }

    int AgentController::RunSessionReader(void* data)
    {
        auto* session = static_cast<ControlSession*>(data);
        auto* controller = session->owner;

        while (session->alive)
        {
            assert(session->buf_head < sizeof(session->buf));
            ssize_t r = platform::net_recv(session->socket, session->buf + session->buf_head,
                                           sizeof(session->buf) - session->buf_head);
            if (r <= 0)
            {
                break;
            }
            size_t total = session->buf_head + r;
            ssize_t consumed = controller->ProcessMessages(session, total);
            if (consumed == -1)
            {
                break;
            }
            if (consumed > 0 && (size_t)consumed < total)
            {
                memmove(session->buf, &session->buf[consumed], total - consumed);
            }
            session->buf_head = total - consumed;
        }

        LOGI("Control client #%d disconnected", session->id);
        util::mutex_lock(session->mutex);
        session->alive = false;
        util::cond_signal(session->cond);
        util::mutex_unlock(session->mutex);

        if (controller->RemoveSessionIfNotStopping(session))
        {
            // close before joining the writer: if it's blocked mid-send(),
            // closesocket() is what aborts that call (shutdown() was observed
            // not to reliably interrupt a concurrent blocking call here)
            platform::close_socket(&session->socket);
            SDL_WaitThread(session->writer_thread, nullptr);
            SDL_DestroyMutex(session->mutex);
            SDL_DestroyCond(session->cond);
            SDL_Thread* self = session->reader_thread;
            delete session;
            if (self)
            {
                SDL_DetachThread(self);
            }
        }
        // else: AgentController::Stop() already claimed this session and will
        // join/close/delete it
        return 0;
    }

    int AgentController::RunAcceptor(void* data)
    {
        auto* controller = static_cast<AgentController*>(data);
        for (;;)
        {
            socket_t client = platform::net_accept(controller->control_server_socket);
            if (client == INVALID_SOCKET)
            {
                break;
            }

            auto* session = new ControlSession();
            session->owner = controller;
            session->socket = client;
            session->id = controller->next_session_id++;
            session->mutex = SDL_CreateMutex();
            session->cond = SDL_CreateCond();
            cbuf_init(&session->queue);

            // writer must be created (and its handle stored) before the reader,
            // since the reader thread reads session->writer_thread at teardown
            // and thread-creation APIs guarantee a new thread sees every write
            // its creator made beforehand -- creating them in the other order
            // would let a reader that disconnects immediately race ahead of the
            // store into session->writer_thread
            session->writer_thread = SDL_CreateThread(RunSessionWriter, "ctrl writer", session);
            session->reader_thread = SDL_CreateThread(RunSessionReader, "ctrl reader", session);

            LOGI("Control client #%d connected", session->id);
            controller->AddSession(session);
        }
        return 0;
    }
}
