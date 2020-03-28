//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_TINY_XPM_HPP
#define ANDROID_IROBOT_TINY_XPM_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"

SDL_Surface *
read_xpm(char *xpm[]);


#endif //ANDROID_IROBOT_TINY_XPM_HPP
