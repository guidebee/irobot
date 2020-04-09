//
// Created by James Shen on 9/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "null_input_manager.hpp"
#include "events.hpp"
#include "util/log.hpp"
#include "util/lock.hpp"
#include "ai/brain.hpp"

namespace irobot::ui {

    enum EventResult NullInputManager::HandleEvent(SDL_Event *event, bool has_screen) {
        switch (event->type) {
            case EVENT_STREAM_STOPPED:
                LOGD("Video stream stopped");
                return EVENT_RESULT_STOPPED_BY_EOS;
            case SDL_QUIT:
                LOGD("User requested to quit");
                return EVENT_RESULT_STOPPED_BY_USER;
            case EVENT_NEW_OPENCV_FRAME:
                ai::ProcessFrame(*this->video_buffer);
                return EVENT_RESULT_CONTINUE;
            case EVENT_NEW_FRAME:
                if (!has_screen) {
                    util::mutex_lock(this->video_buffer->mutex);
                    const AVFrame *frame = this->video_buffer->ConsumeRenderedFrame();
                    struct Size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
                    LOGI("receive new frame %d,%d\n", new_frame_size.width, new_frame_size.height);
                    util::mutex_unlock(this->video_buffer->mutex);
                }
                return EVENT_RESULT_CONTINUE;
            default:
                return EVENT_RESULT_CONTINUE;
        }
    }
}