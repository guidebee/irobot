//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_manager.hpp"
#include "ui/events.hpp"
#include <sys/time.h>
#include "util/log.hpp"
#include "util/lock.hpp"
#include "util/buffer_util.hpp"
#include "platform/net.hpp"
#include "ai/brain.hpp"

namespace irobot::agent {

    bool AgentManager::Init(uint16_t port) {
        this->local_port = port;
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

        initialzied &= this->agent_controller->Init(this->control_server_socket,
                                                    ProcessAgentControlMessage, this);
        return initialzied;
    }

    bool AgentManager::Start() {
        bool started = this->agent_stream->Start();
        started &= this->agent_controller->Start();
        return started;
    }

    void AgentManager::Stop() {
        if (this->video_server_socket != INVALID_SOCKET) {
            platform::close_socket(&this->video_server_socket);
        }
        if (this->control_server_socket != INVALID_SOCKET) {
            platform::close_socket(&this->control_server_socket);
        }
        this->agent_stream->Stop();
        this->agent_controller->Stop();
    }

    void AgentManager::Destroy() {
        this->agent_stream->Destroy();
        this->agent_controller->Destroy();
        LOGD("Agent manager stopped");

    }

    void AgentManager::Join() {
        this->agent_stream->Join();
        this->agent_controller->Join();
    }


    void AgentManager::ProcessAgentControlMessage(void *entity, message::ControlMessage *msg) {
        auto *agent_manager = (AgentManager *) entity;
        switch (msg->type) {
            case message::CONTROL_MSG_TYPE_START_RECORDING:
                agent_manager->StartRecordEvents();
                break;
            case message::CONTROL_MSG_TYPE_END_RECORDING:
                agent_manager->StopRecordEvents();
                break;
            default:
                agent_manager->controller->PushMessage(msg);
        }

    }

    void AgentManager::StartRecordEvents() {
        LOGI("Start event recording...");
        this->fp_events = SDL_RWFromFile(EVENT_FILE_NAME, "w");
        std::string json_str = "[\n";
        char cstr[json_str.size() + 1];
        strcpy(cstr, json_str.c_str());
        SDL_RWwrite(this->fp_events, cstr, strlen(cstr), 1);
    }

    void AgentManager::StopRecordEvents() {
        LOGI("stop event recording...");
        std::string json_str = "{\"event_time\": \"2020-12-12 20:20:20.200\",\n\"msg_type\": \"CONTROL_MSG_TYPE_UNKNOWN\"\n}\n]";
        char cstr[json_str.size() + 1];
        strcpy(cstr, json_str.c_str());
        SDL_RWwrite(this->fp_events, cstr, strlen(cstr), 1);
        SDL_RWclose(this->fp_events);
        this->fp_events = nullptr;
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
                            this->StartRecordEvents();
                        } else {
                            this->StopRecordEvents();
                        }
                    }
                    break;
                case SDLK_k:
                    if (cmd && !shift && !repeat && down) {
                        ai::SaveFrame(*this->video_buffer);
                    }
                    break;
                default:
                    break;

            }

        }
    }

    void AgentManager::SendOpenCVImage(message::BlobMessageType type,int max_size, bool color){
        auto mat = ai::ConvertToMat(*this->video_buffer, max_size,
                                    color);

        unsigned char *data = mat.data;
        int width = mat.size().width;
        int height = mat.size().height;
        int length = mat.total() * mat.elemSize();

        struct message::BlobMessage msg{};
        msg.type = type;
        struct timeval tm_now{};
        gettimeofday(&tm_now, nullptr);
        Uint64 milli_seconds = tm_now.tv_sec * 1000LL + tm_now.tv_usec / 1000;
        msg.timestamp = milli_seconds;
        msg.id = 0;
        msg.count = 1;
        Uint64 size = length + 16;

        msg.buffers[0].data = (unsigned char *) SDL_malloc(size);
        if (msg.buffers[0].data != nullptr) {
            util::buffer_write64be(msg.buffers[0].data, (uint64_t) width);
            util::buffer_write64be(msg.buffers[0].data + 8, (uint64_t) height);
            memcpy(msg.buffers[0].data + 16, data, length);
            msg.buffers[0].length = size;
            this->agent_stream->PushMessage(&msg);

        } else {
            LOGW("Unable to allow memory");
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
                util::mutex_lock(this->video_buffer->mutex);
                LOGD("Agent Manager received Opencv Frame %d", this->video_buffer->frame_number);
                {
                    this->SendOpenCVImage(message::BLOB_MSG_TYPE_OPENCV_MAT,800,false);
                    this->SendOpenCVImage(message::BLOB_MSG_TYPE_SCREEN_SHOT,240,true);
                }
                util::mutex_unlock(this->video_buffer->mutex);
                return ui::EVENT_RESULT_CONTINUE;
            case EVENT_NEW_FRAME:
                if (!has_screen) {
                    util::mutex_lock(this->video_buffer->mutex);
                    this->video_buffer->ConsumeRenderedFrame();
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