//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_CONTROLLER_HPP
#define ANDROID_IROBOT_AGENT_CONTROLLER_HPP

#include <cassert>
#include <vector>

#include "core/actor.hpp"
#include "platform/net.hpp"
#include "message/control_msg.hpp"
#include "util/cbuf.hpp"

namespace irobot::agent
{
    class AgentController;

    // a fully framed ([4-byte BE length][JSON payload]) outbound message,
    // ready to write to a socket as-is. PushMessage() serializes a
    // ControlMessage into one of these exactly once, then hands a copy to
    // every session's queue -- ControlMessage itself can own heap pointers
    // (e.g. clipboard text), so broadcasting the struct by value into N
    // queues and destroying N shallow copies would double-free; a byte
    // buffer has no such ownership ambiguity and copies cleanly.
    struct ControlFrame
    {
        std::vector<unsigned char> bytes;
    };

    struct ControlFrameQueue CBUF(ControlFrame, 64);

    // one accepted control connection: owns its socket exclusively for its
    // whole lifetime -- either the session's own reader thread tears it down
    // (ordinary client disconnect), or AgentController::Stop() does (app
    // shutdown), never both -- see agent_controller.cpp for the handoff rule
    struct ControlSession
    {
        AgentController* owner = nullptr;
        socket_t socket = INVALID_SOCKET;
        int id = 0;
        SDL_Thread* reader_thread = nullptr;
        SDL_Thread* writer_thread = nullptr;
        SDL_mutex* mutex = nullptr;
        SDL_cond* cond = nullptr;
        bool alive = true;
        ControlFrameQueue queue{};
        // partial-frame buffer for the [4-byte BE length][JSON] wire framing --
        // per-session because each connection parses its own byte stream
        unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE * 2]{};
        size_t buf_head = 0;
    };

    class AgentController : public Actor
    {
    public:
        socket_t control_server_socket = INVALID_SOCKET;
        message::MessageHandler message_handler = nullptr;
        void* entity = nullptr;

        bool Init(socket_t server_socket,
                  message::MessageHandler message_handler, void* entity);

        bool Start() override;

        void Stop() override;

        void Join() override;

        void Destroy() override;

        // broadcasts msg to every connected client session
        bool PushMessage(const message::ControlMessage* msg);

        static int RunAcceptor(void* data);

        static int RunSessionReader(void* data);

        static int RunSessionWriter(void* data);

    private:
        std::vector<ControlSession*> sessions;
        SDL_mutex* sessions_mutex = nullptr;
        int next_session_id = 1;
        bool stopping = false;

        void AddSession(ControlSession* session);

        // returns true if the caller (the session's own reader thread) owns
        // tearing this session down; false means Stop() already claimed it
        bool RemoveSessionIfNotStopping(ControlSession* session);

        static bool BuildFrame(const message::ControlMessage* msg, std::vector<unsigned char>& out);

        ssize_t ProcessMessages(ControlSession* session, size_t len);

        void ProcessMessage(message::ControlMessage* msg);
    };
}

#endif //ANDROID_IROBOT_AGENT_CONTROLLER_HPP
