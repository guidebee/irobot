//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_EVENTS_HPP
#define ANDROID_IROBOT_EVENTS_HPP

#define EVENT_NEW_FRAME                 (SDL_USEREVENT + 1)
#define EVENT_STREAM_STOPPED            (SDL_USEREVENT + 2)
#define EVENT_NEW_OPENCV_FRAME          (SDL_USEREVENT + 3)
#define EVENT_START_RECORD_UI_EVENT     (SDL_USEREVENT + 4)
#define EVENT_END_RECORD_UI_EVENT       (SDL_USEREVENT + 5)
#define EVENT_NEW_DATA_STREAM_CONNECTION                 (SDL_USEREVENT + 6)

namespace irobot::ui {

    enum EventResult {
        EVENT_RESULT_CONTINUE,
        EVENT_RESULT_STOPPED_BY_USER,
        EVENT_RESULT_STOPPED_BY_EOS,
    };
}

#endif //ANDROID_IROBOT_EVENTS_HPP
