//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_manager.hpp"
#include "ui/events.hpp"

#include "util/log.hpp"
#include "util/lock.hpp"
#include "platform/net.hpp"
#include "ai/brain.hpp"

namespace irobot::agent {

    bool AgentManager::Init(uint16_t port) {
        this->local_port = port;
        (*this->agent_stream) = AgentStream{};
        (*this->agent_controller) = AgentController{};

        this->control_server_socket = platform::listen_on_port(this->local_port + 1);
        if (this->control_server_socket == INVALID_SOCKET) {
            LOGE("Could not listen on control server port %" PRIu16,
                 (unsigned short) (this->local_port + 1));
            return false;
        }
        this->video_server_socket = platform::listen_on_port(this->local_port + 2);
        if (this->video_server_socket == INVALID_SOCKET) {
            LOGE("Could not listen on video server port %" PRIu16,
                 (unsigned short) (this->local_port + 2));
            return false;
        }
        bool initialzied = this->agent_stream->Init(this->video_server_socket);
        initialzied &= this->agent_controller->Init(this->control_server_socket);
        return initialzied;
    }

    bool AgentManager::Start() {
        bool started = this->agent_stream->Start();
        started &= this->agent_controller->Start();
        return started;
    }

    void AgentManager::Stop() {
        this->agent_stream->Stop();
        this->agent_controller->Stop();
    }

    void AgentManager::Destroy() {
        this->agent_stream->Destroy();
        this->agent_controller->Destroy();
        if (this->video_server_socket != INVALID_SOCKET) {
            platform::close_socket(&this->video_server_socket);
        }
        if (this->control_server_socket != INVALID_SOCKET) {
            platform::close_socket(&this->control_server_socket);
        }

    }

    void AgentManager::Join() {
        this->agent_stream->Join();
        this->agent_controller->Join();
    }

    void AgentManager::ProcessKey(const SDL_KeyboardEvent *event) {
        // control: indicates the state of the command-line option --no-control
        // ctrl: the Ctrl key

        bool ctrl = event->keysym.mod & (KMOD_LCTRL | KMOD_RCTRL);
        bool alt = event->keysym.mod & (KMOD_LALT | KMOD_RALT);
        bool meta = event->keysym.mod & (KMOD_LGUI | KMOD_RGUI);

        // use Cmd on macOS, Ctrl on other platforms
#ifdef __APPLE__
        bool cmd = !ctrl && meta;
#else
        if (meta) {
        // no shortcuts involve Meta on platforms other than macOS, and it must
        // not be forwarded to the device
        return;
    }
    bool cmd = ctrl; // && !meta, already guaranteed
#endif

        if (alt) {
            // no shortcuts involve Alt, and it must not be forwarded to the device
            return;
        }

        // capture all Ctrl events
        if (ctrl || cmd) {
            SDL_Keycode keycode = event->keysym.sym;
            bool down = event->type == SDL_KEYDOWN;

            bool repeat = event->repeat;
            bool shift = event->keysym.mod & (KMOD_LSHIFT | KMOD_RSHIFT);
            switch (keycode) {
                case SDLK_e:
                    if (cmd && !shift && !repeat && down) {
                        if (this->fp_events == nullptr) {
                            LOGI("Start event recording...");
                            this->fp_events = SDL_RWFromFile(EVENT_FILE_NAME, "w");
                            std::string json_str = "[\n";
                            char cstr[json_str.size() + 1];
                            strcpy(cstr, json_str.c_str());
                            SDL_RWwrite(this->fp_events, cstr, strlen(cstr), 1);
                        } else {
                            LOGI("stop event recording...");
                            std::string json_str = "{\"event_time\": \"2020-12-12 20:20:20.200\",\n\"msg_type\": \"CONTROL_MSG_TYPE_UNKNOWN\"\n}\n]";
                            char cstr[json_str.size() + 1];
                            strcpy(cstr, json_str.c_str());
                            SDL_RWwrite(this->fp_events, cstr, strlen(cstr), 1);
                            SDL_RWclose(this->fp_events);
                            this->fp_events = nullptr;
                        }
                    }
                    break;
                case SDLK_k:
                    if (cmd && !shift && !repeat && down) {
                        ai::ProcessFrame(*this->video_buffer);
                    }
                    break;
                default:
                    break;

            }

        }
    }


    ui::EventResult AgentManager::HandleEvent(SDL_Event *event, bool has_screen) {
        switch (event->type) {
            case EVENT_STREAM_STOPPED:
                LOGD("Video stream stopped");
                return ui::EVENT_RESULT_STOPPED_BY_EOS;
            case SDL_QUIT:
                LOGD("User requested to quit");
                return ui::EVENT_RESULT_STOPPED_BY_USER;
            case EVENT_NEW_OPENCV_FRAME:

                return ui::EVENT_RESULT_CONTINUE;
            case EVENT_NEW_FRAME:
                if (!has_screen) {
                    util::mutex_lock(this->video_buffer->mutex);
                    const AVFrame *frame = this->video_buffer->ConsumeRenderedFrame();
                    struct Size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
                    LOGI("receive new frame %d,%d\n", new_frame_size.width, new_frame_size.height);
                    util::mutex_unlock(this->video_buffer->mutex);
                }
                return ui::EVENT_RESULT_CONTINUE;
            case SDL_KEYDOWN:
            case SDL_KEYUP:
                this->ProcessKey(&event->key);
                return ui::EVENT_RESULT_CONTINUE;
            default:
                return ui::EVENT_RESULT_CONTINUE;
        }
    }

    bool AgentManager::PushDeviceControlMessage(const message::ControlMessage *msg) {
        if (this->fp_events) {
            auto json_str = ((message::ControlMessage *) msg)->JsonSerialize();
            json_str += ",\n";
            char cstr[json_str.size() + 1];
            strcpy(cstr, json_str.c_str());
            SDL_RWwrite(this->fp_events, cstr, strlen(cstr), 1);

        }
        return this->controller->PushMessage(msg);
    }
}