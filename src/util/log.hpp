//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//


#pragma ide diagnostic ignored "OCUnusedMacroInspection"
#ifndef ANDROID_IROBOT_LOG_HPP
#define ANDROID_IROBOT_LOG_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_log.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"

#define LOGV(...) SDL_LogVerbose(SDL_LOG_CATEGORY_APPLICATION, __VA_ARGS__)
#define LOGD(...) SDL_LogDebug(SDL_LOG_CATEGORY_APPLICATION, __VA_ARGS__)
#define LOGI(...) SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION, __VA_ARGS__)
#define LOGW(...) SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION, __VA_ARGS__)
#define LOGE(...) SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, __VA_ARGS__)
#define LOGC(...) SDL_LogCritical(SDL_LOG_CATEGORY_APPLICATION, __VA_ARGS__)

#endif //ANDROID_IROBOT_LOG_HPP

