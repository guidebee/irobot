//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "file_handler.hpp"

#include <cassert>

#include "platform/command.hpp"
#include "util/lock.hpp"
#include "util/log.hpp"

#define DEFAULT_PUSH_TARGET "/sdcard/"

namespace irobot::android {

    bool FileHandler::Init(const char *serial,
                           const char *push_target) {

        cbuf_init(&this->queue);
        if (!(this->mutex = SDL_CreateMutex())) {
            return false;
        }

        if (!(this->event_cond = SDL_CreateCond())) {
            SDL_DestroyMutex(this->mutex);
            return false;
        }

        if (serial) {
            this->serial = SDL_strdup(serial);
            if (!this->serial) {
                LOGW("Could not strdup serial");
                SDL_DestroyCond(this->event_cond);
                SDL_DestroyMutex(this->mutex);
                return false;
            }
        } else {
            this->serial = nullptr;
        }

        // lazy initialization
        this->initialized = false;

        this->stopped = false;
        this->current_process = PROCESS_NONE;
        this->push_target = push_target ? push_target : DEFAULT_PUSH_TARGET;
        return true;
    }

    void FileHandler::Destroy() {
        SDL_DestroyCond(this->event_cond);
        SDL_DestroyMutex(this->mutex);
        SDL_free(this->serial);

        struct FileHandlerRequest req{};
        while (cbuf_take(&this->queue, &req)) {
            req.destroy();
        }
    }


    bool FileHandler::Request(
            FileHandlerActionType action, char *file) {

        // start file_handler if it's used for the first time
        if (!this->initialized) {
            if (!this->Start()) {
                return false;
            }
            this->initialized = true;
        }

        LOGI("Request to %s %s", action == ACTION_INSTALL_APK ? "install" : "push",
             file);
        struct FileHandlerRequest req = {
                .action = action,
                .file = file,
        };

        util::mutex_lock(this->mutex);
        bool was_empty = cbuf_is_empty(&this->queue);
        bool res = cbuf_push(&this->queue, req);
        if (was_empty) {
            util::cond_signal(this->event_cond);
        }
        util::mutex_unlock(this->mutex);
        return res;
    }


    bool FileHandler::Start() {
        LOGD("Starting file_handler thread");
        this->thread = SDL_CreateThread(FileHandler::RunFileHandler, "file_handler",
                                        this);
        if (!this->thread) {
            LOGC("Could not start file_handler thread");
            return false;
        }
        return true;
    }

    void FileHandler::Stop() {
        util::mutex_lock(this->mutex);
        this->stopped = true;
        util::cond_signal(this->event_cond);
        if (this->current_process != PROCESS_NONE) {
            if (!irobot::platform::cmd_terminate(this->current_process)) {
                LOGW("Could not terminate install process");
            }
            irobot::platform::cmd_simple_wait(this->current_process, nullptr);
            this->current_process = PROCESS_NONE;
        }
        util::mutex_unlock(this->mutex);
    }

    void FileHandler::Join() {
        SDL_WaitThread(this->thread, nullptr);
    }

    int FileHandler::RunFileHandler(void *data) {
        auto *file_handler = (FileHandler *) data;

        for (;;) {
            util::mutex_lock(file_handler->mutex);
            file_handler->current_process = PROCESS_NONE;
            while (!file_handler->stopped && cbuf_is_empty(&file_handler->queue)) {
                util::cond_wait(file_handler->event_cond, file_handler->mutex);
            }
            if (file_handler->stopped) {
                // stop immediately, do not process further events
                util::mutex_unlock(file_handler->mutex);
                break;
            }
            struct FileHandlerRequest req{};
            bool non_empty = cbuf_take(&file_handler->queue, &req);
            assert(non_empty);
            (void) non_empty;

            ProcessType process;
            if (req.action == ACTION_INSTALL_APK) {
                LOGI("Installing %s...", req.file);
                process = InstallApk(file_handler->serial, req.file);
            } else {
                LOGI("Pushing %s...", req.file);
                process = PushFile(file_handler->serial, req.file,
                                   file_handler->push_target);
            }
            file_handler->current_process = process;
            util::mutex_unlock(file_handler->mutex);

            if (req.action == ACTION_INSTALL_APK) {
                if (irobot::platform::process_check_success(process, "adb install")) {
                    LOGI("%s successfully installed", req.file);
                } else {
                    LOGE("Failed to install %s", req.file);
                }
            } else {
                if (irobot::platform::process_check_success(process, "adb push")) {
                    LOGI("%s successfully pushed to %s", req.file,
                         file_handler->push_target);
                } else {
                    LOGE("Failed to push %s to %s", req.file,
                         file_handler->push_target);
                }
            }

            req.destroy();
        }
        return 0;
    }

    ProcessType FileHandler::InstallApk(const char *serial, const char *file) {
        return platform::adb_install(serial, file);
    }

    ProcessType FileHandler::PushFile(const char *serial,
                                      const char *file, const char *push_target) {
        return platform::adb_push(serial, file, push_target);
    }

}