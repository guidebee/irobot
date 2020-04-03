//
// Created by James Shen on 30/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_IROBOT_UI_HPP
#define ANDROID_IROBOT_IROBOT_UI_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL.h>

#if defined (__cplusplus)
}
#endif

bool sdl_init_and_configure(bool display);

int event_watcher(void *data, SDL_Event *event);

bool event_loop(bool display, bool control);

#endif //ANDROID_IROBOT_IROBOT_UI_HPP
