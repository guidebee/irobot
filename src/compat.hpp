//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_COMPAT_HPP
#define ANDROID_IROBOT_COMPAT_HPP

#if defined (__cplusplus)
extern "C" {
#endif
#include <libavformat/version.h>
#include <SDL2/SDL_version.h>

#if defined (__cplusplus)
}
#endif


#if SDL_VERSION_ATLEAST(2, 0, 5)
// <https://wiki.libsdl.org/SDL_HINT_MOUSE_FOCUS_CLICKTHROUGH>
# define SCRCPY_SDL_HAS_HINT_MOUSE_FOCUS_CLICKTHROUGH
// <https://wiki.libsdl.org/SDL_GetDisplayUsableBounds>
# define SCRCPY_SDL_HAS_GET_DISPLAY_USABLE_BOUNDS
// <https://wiki.libsdl.org/SDL_WindowFlags>
# define SCRCPY_SDL_HAS_WINDOW_ALWAYS_ON_TOP
#endif




#endif //ANDROID_IROBOT_COMPAT_HPP
