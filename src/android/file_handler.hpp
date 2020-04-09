//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_FILE_HANDLER_HPP
#define ANDROID_IROBOT_FILE_HANDLER_HPP

#include "core/actor.hpp"
#include "platform/command.hpp"
#include "util/cbuf.hpp"

namespace irobot::android {

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

    struct FileHandlerRequestQueue CBUF(FileHandlerRequest, 16);

    class FileHandler : public Actor {

    public:
        char *serial = nullptr;
        const char *push_target = nullptr;
        bool initialized = false;
        ProcessType current_process{};
        FileHandlerRequestQueue queue{};

        bool Init(const char *pSerial, const char *pPush_target);

        void Destroy() override;

        bool Start() override;

        void Stop() override;

        // take ownership of file, and will SDL_free() it
        bool Request(FileHandlerActionType action, char *file);

        static int RunFileHandler(void *data);

        static ProcessType InstallApk(const char *serial, const char *file);

        static ProcessType PushFile(const char *serial, const char *file,
                                    const char *push_target);

    };
}
#endif //ANDROID_IROBOT_FILE_HANDLER_HPP
