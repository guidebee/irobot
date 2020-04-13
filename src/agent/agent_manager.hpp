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
#include "image_hash/phash.hpp"
#include "ui/events.hpp"
#include "video/video_buffer.hpp"

#define EVENT_FILE_NAME "events.json"

namespace irobot::agent {

    class AgentManager { // implements all methods of Actor

    public:

        video::VideoBuffer *video_buffer = nullptr;
        SDL_RWops *fp_events = nullptr;
        socket_t video_server_socket = INVALID_SOCKET;;
        socket_t control_server_socket = INVALID_SOCKET;;
        uint16_t local_port = 0;

        // the following are sub classes of Actor (4 threads)
        Controller *controller = nullptr;
        AgentController *agent_controller = nullptr; // (2 threads)
        AgentStream *agent_stream = nullptr;

        bool Init(uint16_t port);

        bool Start();

        void Stop();

        void Destroy();

        void Join();

        void SendOpenCVImage(message::BlobMessageType type, int size, bool color);

        ui::EventResult HandleEvent(SDL_Event *event, bool has_screen);

        bool PushDeviceControlMessage(const message::ControlMessage *msg); // Agent-->Device

        cv::Ptr<cv::img_hash::ImgHashBase> phash_func;

    private:
        void ProcessKey(const SDL_KeyboardEvent *event);

        static void ProcessAgentControlMessage(void *entity, message::ControlMessage *msg); //Client<--Agent

        void StartRecordEvents();

        void StopRecordEvents();


    };


}
#endif //ANDROID_IROBOT_AGENT_MANAGER_HPP
