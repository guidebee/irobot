//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_stream.hpp"

#include <algorithm>
#include <cassert>
#include <SDL2/SDL_events.h>

#include "ui/events.hpp"
#include "util/lock.hpp"
#include "util/log.hpp"

namespace irobot::agent
{
    unsigned char data_buffer[BLOB_MSG_SERIALIZED_MAX_SIZE];

    bool AgentStream::Init(socket_t socket)
    {
        cbuf_init(&this->queue);
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
        this->video_server_socket = socket;
        this->stopped = false;
        return true;
    }

    void AgentStream::AddSession(VideoSession* session)
    {
        util::mutex_lock(this->sessions_mutex);
        this->sessions.push_back(session);
        std::vector<unsigned char> catch_up = this->last_resolution_frame;
        bool send_catch_up = this->has_resolution;
        util::mutex_unlock(this->sessions_mutex);

        if (send_catch_up)
        {
            // unicast the current resolution to this session right away --
            // AgentManager only re-broadcasts it when it *changes*, so a
            // session joining after the first one would otherwise never see it
            platform::net_send_all(session->socket, catch_up.data(), catch_up.size());
        }

        static SDL_Event new_opencv_frame_event = {
            .type = EVENT_NEW_OPENCV_FRAME,
        };
        SDL_PushEvent(&new_opencv_frame_event);
    }

    void AgentStream::RemoveAndCloseSession(VideoSession* session)
    {
        // RunStream (the only caller) may be broadcasting a snapshot that
        // Stop() is concurrently tearing down -- if Stop() has already
        // claimed ownership (stopping == true), it will close/delete this
        // session itself once it joins RunStream, so back off here rather
        // than risk a double-close/double-free
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

        if (owner_self)
        {
            LOGI("Video client #%d disconnected", session->id);
            platform::close_socket(&session->socket);
            delete session;
        }
    }

    void AgentStream::Destroy()
    {
        Actor::Destroy();
        SDL_DestroyMutex(this->sessions_mutex);
        message::BlobMessage msg{};
        while (cbuf_take(&this->queue, &msg))
        {
            msg.Destroy();
        }
        LOGI("Agent stream stopped");
    }

    bool AgentStream::PushMessage(
        const message::BlobMessage* msg)
    {
        util::mutex_lock(this->mutex);
        bool was_full = cbuf_is_full(&this->queue);
        if (!was_full)
        {
            bool was_empty = cbuf_is_empty(&this->queue);
            bool res = cbuf_push(&this->queue, *msg);
            if (was_empty)
            {
                util::cond_signal(this->thread_cond);
            }
            util::mutex_unlock(this->mutex);
            return res;
        }
        else
        {
            LOGD("Queue is full,skip video frame");
            return false;
        }
    }

    float AgentStream::GetTransferSpeed()
    {
        Uint32 currentTime = SDL_GetTicks();
        auto speed = (float)((double)(this->total_bytes) /
            (double)(currentTime - this->start_ticks) * 1000.0 / (1024.0 * 1024.0));
        auto delta = currentTime - this->last_ticks;
        if (delta > 5000)
        {
            LOGI("Video transfer speed: %.2fM/s  %.3fG in %.1f seconds with %.1f fps\n", speed,
                 this->total_bytes / (1024.0 * 1024.0 * 1024.0),
                 (float)(currentTime - this->start_ticks) / 1000.0,
                 (float)this->total_frame * 500.0 / ((float)(currentTime - this->start_ticks)));
            this->last_ticks = currentTime;
        }
        return speed;
    }

    bool AgentStream::IsConnected()
    {
        util::mutex_lock(this->sessions_mutex);
        bool connected = !this->sessions.empty();
        util::mutex_unlock(this->sessions_mutex);
        return connected;
    }

    int AgentStream::RunAcceptor(void* data)
    {
        auto* stream = static_cast<AgentStream*>(data);
        for (;;)
        {
            socket_t client = platform::net_accept(stream->video_server_socket);
            if (client == INVALID_SOCKET)
            {
                break;
            }
            if (stream->stopped)
            {
                // shutting down: don't hand Stop() a session it never
                // snapshotted -- just drop this straggler connection
                platform::close_socket(&client);
                continue;
            }

            auto* session = new VideoSession();
            session->socket = client;
            session->id = stream->next_session_id++;
            LOGI("Video client #%d connected", session->id);
            stream->AddSession(session);
        }
        return 0;
    }

    int AgentStream::RunStream(void* data)
    {
        auto* stream = static_cast<AgentStream*>(data);

        for (;;)
        {
            util::mutex_lock(stream->mutex);
            while (!stream->stopped && cbuf_is_empty(&stream->queue))
            {
                util::cond_wait(stream->thread_cond, stream->mutex);
            }
            if (stream->stopped)
            {
                // stop immediately, do not process further msgs
                util::mutex_unlock(stream->mutex);
                break;
            }
            message::BlobMessage msg{};
            bool non_empty = cbuf_take(&stream->queue, &msg);
            assert(non_empty);
            (void)non_empty;
            util::mutex_unlock(stream->mutex);

            size_t length = msg.Serialize(data_buffer);
            if (length)
            {
                if (msg.type == message::BLOB_MSG_TYPE_RESOLUTION)
                {
                    util::mutex_lock(stream->sessions_mutex);
                    stream->last_resolution_frame.assign(data_buffer, data_buffer + length);
                    stream->has_resolution = true;
                    util::mutex_unlock(stream->sessions_mutex);
                }

                util::mutex_lock(stream->sessions_mutex);
                std::vector<VideoSession*> snapshot = stream->sessions;
                util::mutex_unlock(stream->sessions_mutex);

                for (VideoSession* session : snapshot)
                {
                    int w = platform::net_send_all(session->socket, data_buffer, length);
                    if (w != (int)length)
                    {
                        stream->RemoveAndCloseSession(session);
                    }
                }

                stream->total_bytes += length;
                stream->total_frame += 1;
                stream->GetTransferSpeed();
            }
            msg.Destroy();
        }
        return 0;
    }

    void AgentStream::Stop()
    {
        util::mutex_lock(this->sessions_mutex);
        this->stopping = true;
        for (VideoSession* session : this->sessions)
        {
            // closesocket() -- not shutdown() -- is what reliably aborts a
            // concurrent blocking send() RunStream may be doing (shutdown()
            // alone was observed not to reliably interrupt a blocked call)
            platform::close_socket(&session->socket);
        }
        util::mutex_unlock(this->sessions_mutex);

        // wakes RunStream out of cond_wait if it's idle between messages
        Actor::Stop();

        // RunStream will not touch a session again once it observes
        // `stopped` (checked between messages) or a shut-down send() fails
        // (RemoveAndCloseSession then becomes a no-op, since `stopping` is
        // set) -- joining it here, before the close/delete pass below,
        // guarantees no send() can still be in flight against a session
        // this function is about to free
        SDL_WaitThread(this->thread, nullptr);
        this->thread = nullptr;

        util::mutex_lock(this->sessions_mutex);
        std::vector<VideoSession*> snapshot = std::move(this->sessions);
        this->sessions.clear();
        util::mutex_unlock(this->sessions_mutex);

        for (VideoSession* session : snapshot)
        {
            // already closed above, before RunStream was joined
            delete session;
        }
    }

    void AgentStream::Join()
    {
        if (this->thread)
        {
            SDL_WaitThread(this->thread, nullptr);
        }
        SDL_WaitThread(this->acceptor_thread, nullptr);
    }

    bool AgentStream::Start()
    {
        this->start_ticks = SDL_GetTicks();
        LOGI("Starting agent stream acceptor thread");
        this->acceptor_thread = SDL_CreateThread(RunAcceptor, "agent stream acceptor",
                                                 this);
        if (!this->acceptor_thread)
        {
            LOGC("Could not start agent stream acceptor thread");
            return false;
        }

        LOGD("Starting agent stream thread");
        this->thread = SDL_CreateThread(RunStream, "agent stream",
                                        this);
        if (!this->thread)
        {
            LOGC("Could not start agent stream thread");
            return false;
        }


        return true;
    }
}
