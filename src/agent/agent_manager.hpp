//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AGENT_MANAGER_HPP
#define ANDROID_IROBOT_AGENT_MANAGER_HPP

#include <SDL2/SDL_events.h>

#include "agent/agent_controller.hpp"
#include "agent/agent_stream.hpp"
#include "core/controller.hpp"
#include <opencv2/core.hpp>
#include "ui/events.hpp"
#include "video/video_buffer.hpp"

#define EVENT_FILE_NAME "events.json"

namespace irobot::agent
{
    class AgentManager
    {
        // implements all methods of Actor

    public:
        video::VideoBuffer* video_buffer = nullptr;
        SDL_RWops* fp_events = nullptr;
        socket_t video_server_socket = INVALID_SOCKET;;
        socket_t control_server_socket = INVALID_SOCKET;;
        uint16_t local_port = 0;

        // the following are sub classes of Actor (4 threads)
        Controller* controller = nullptr;
        AgentController* agent_controller = nullptr; // (2 threads)
        AgentStream* agent_stream = nullptr;

        // last resolution sent via SendResolution() -- public (not private)
        // because AgentManager is constructed as an aggregate with designated
        // initializers (see irobot_core.cpp); a private non-static data member
        // would make it a non-aggregate and break that construction
        int last_resolution_width = 0;
        int last_resolution_height = 0;

        bool Init(uint16_t port);

        bool Start();

        void Stop();

        void Destroy();

        void Join();

        void SendOpenCVImage(message::BlobMessageType type, int size, bool color);

        // sends the real, undownscaled device resolution as a
        // BLOB_MSG_TYPE_RESOLUTION blob (only when it differs from the last
        // resolution sent, to avoid repeating it every frame -- see
        // agent_manager.cpp for why this value matters to an agent client)
        void SendResolution();

        ui::EventResult HandleEvent(SDL_Event* event, bool has_screen);

        bool PushDeviceControlMessage(const message::ControlMessage* msg); // Agent-->Device


    private:
        void ProcessKey(const SDL_KeyboardEvent* event);

        static void ProcessAgentControlMessage(void* entity, message::ControlMessage* msg); //Client<--Agent

        void StartRecordEvents();

        void StopRecordEvents();
    };
}
#endif //ANDROID_IROBOT_AGENT_MANAGER_HPP
