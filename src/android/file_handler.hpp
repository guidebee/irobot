//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_FILE_HANDLER_HPP
#define ANDROID_IROBOT_FILE_HANDLER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "command.hpp"

#include "util/cbuf.hpp"

typedef enum {
    ACTION_INSTALL_APK,
    ACTION_PUSH_FILE,
} FileHandlerActionType;

struct FileHandlerRequest {
    FileHandlerActionType action;
    char *file;
};

struct FileHandlerRequestQueue CBUF(struct FileHandlerRequest, 16);

class FileHandler {
public:
    char *serial;
    const char *push_target;
    SDL_Thread *thread;
    SDL_mutex *mutex;
    SDL_cond *event_cond;
    bool stopped;
    bool initialized;
    process_t current_process;
    struct FileHandlerRequestQueue queue;

    bool
    init( const char *serial,
                      const char *push_target);

    void
    destroy();

    bool
    start();

    void
    stop();

    void
    join();

// take ownership of file, and will SDL_free() it
    bool
    request(
                         FileHandlerActionType action,
                         char *file);
};



#endif //ANDROID_IROBOT_FILE_HANDLER_HPP
