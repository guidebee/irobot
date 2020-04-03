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
#include "platform/command.hpp"

#include "util/cbuf.hpp"

typedef enum {
    ACTION_INSTALL_APK,
    ACTION_PUSH_FILE,
} FileHandlerActionType;

struct FileHandlerRequest {

    FileHandlerActionType action;
    char *file;

    inline void destroy() {
        SDL_free(this->file);
    }
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
    ProcessType current_process;
    struct FileHandlerRequestQueue queue;

    bool init(const char *serial, const char *push_target);

    void destroy();

    bool start();

    void stop();

    void join();

    // take ownership of file, and will SDL_free() it
    bool request(FileHandlerActionType action, char *file);

    static int run_file_handler(void *data);

    static ProcessType
    install_apk(const char *serial, const char *file) {
        return adb_install(serial, file);
    }

    static ProcessType
    push_file(const char *serial, const char *file, const char *push_target) {
        return adb_push(serial, file, push_target);
    }

};

#endif //ANDROID_IROBOT_FILE_HANDLER_HPP
