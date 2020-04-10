//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "agent_manager.hpp"
#include "ui/events.hpp"

#include "util/log.hpp"
#include "util/lock.hpp"
#include "ai/brain.hpp"

namespace irobot::agent {


    ui::EventResult AgentManager::HandleEvent(SDL_Event *event, bool has_screen) {
        switch (event->type) {
            case EVENT_STREAM_STOPPED:
                LOGD("Video stream stopped");
                return ui::EVENT_RESULT_STOPPED_BY_EOS;
            case SDL_QUIT:
                LOGD("User requested to quit");
                return ui::EVENT_RESULT_STOPPED_BY_USER;
            case EVENT_NEW_OPENCV_FRAME:
                ai::ProcessFrame(*this->video_buffer);
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
            default:
                return ui::EVENT_RESULT_CONTINUE;
        }
    }
}