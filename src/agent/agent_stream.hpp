//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_STREAM_HPP
#define ANDROID_IROBOT_AGENT_STREAM_HPP

#include <SDL2/SDL_timer.h>
#include <vector>

#include "core/actor.hpp"
#include "util/cbuf.hpp"
#include "platform/net.hpp"
#include "message/blob_msg.hpp"

namespace irobot::agent
{
    // one accepted video connection. Video is push-only (server -> client),
    // so unlike the control channel there is no reader thread: a session is
    // torn down inline, by the single broadcasting thread, the moment a
    // send() to it fails -- see AgentStream::RunStream in agent_stream.cpp
    struct VideoSession
    {
        socket_t socket = INVALID_SOCKET;
        int id = 0;
    };

    class AgentStream : public Actor
    {
    public:
        socket_t video_server_socket = INVALID_SOCKET;
        message::BlobMessageQueue queue{};

        // fully-serialized bytes of the last BLOB_MSG_TYPE_RESOLUTION frame
        // broadcast -- cached so a newly connected session can be sent the
        // current resolution immediately, independent of AgentManager's
        // send-only-on-change gate (which only re-broadcasts to sessions
        // already connected when the resolution changes)
        std::vector<unsigned char> last_resolution_frame;
        bool has_resolution = false;

        bool Init(socket_t server_socket);

        void Destroy() override;

        void Join() override;

        void Stop() override;

        bool Start() override;

        bool PushMessage(const message::BlobMessage* msg);

        bool IsConnected();

        float GetTransferSpeed();

        static int RunAcceptor(void* data);

        static int RunStream(void* data);

    private:
        std::vector<VideoSession*> sessions;
        SDL_mutex* sessions_mutex = nullptr;
        SDL_Thread* acceptor_thread = nullptr;
        int next_session_id = 1;
        bool stopping = false;
        unsigned long total_bytes = 0;
        unsigned long total_frame = 0;
        Uint32 start_ticks = 0;
        Uint32 last_ticks = 0;

        void AddSession(VideoSession* session);

        void RemoveAndCloseSession(VideoSession* session);
    };
}

#endif //ANDROID_IROBOT_AGENT_STREAM_HPP
