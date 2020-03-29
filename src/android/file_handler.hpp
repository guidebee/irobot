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
} file_handler_action_t;

struct file_handler_request {
    file_handler_action_t action;
    char *file;
};

struct file_handler_request_queue CBUF(struct file_handler_request, 16);

struct file_handler {
    char *serial;
    const char *push_target;
    SDL_Thread *thread;
    SDL_mutex *mutex;
    SDL_cond *event_cond;
    bool stopped;
    bool initialized;
    process_t current_process;
    struct file_handler_request_queue queue;
};

bool
file_handler_init(struct file_handler *file_handler, const char *serial,
                  const char *push_target);

void
file_handler_destroy(struct file_handler *file_handler);

bool
file_handler_start(struct file_handler *file_handler);

void
file_handler_stop(struct file_handler *file_handler);

void
file_handler_join(struct file_handler *file_handler);

// take ownership of file, and will SDL_free() it
bool
file_handler_request(struct file_handler *file_handler,
                     file_handler_action_t action,
                     char *file);

#endif //ANDROID_IROBOT_FILE_HANDLER_HPP
