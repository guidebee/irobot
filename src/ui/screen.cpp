//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "screen.hpp"
#include <cassert>
#include "core/common.hpp"
#include "android/file_handler.hpp"
#include "video/video_buffer.hpp"
#include "util/lock.hpp"
#include "util/log.hpp"
#include "ui/events.hpp"
#include "ui/input_manager.hpp"

#define DISPLAY_MARGINS 96

namespace irobot {

    extern ui::Screen screen;
    extern ui::InputManager input_manager;
    extern video::VideoBuffer video_buffer;
    extern android::FileHandler file_handler;

    namespace ui {

        // get the window size in a struct size
        struct Size Screen::GetWindowSize(SDL_Window *window) {
            int width;
            int height;
            SDL_GetWindowSize(window, &width, &height);

            struct Size size{};
            size.width = width;
            size.height = height;
            return size;
        }

        // get the windowed window size
        struct Size Screen::GetWindowedWindowSize() {
            if (this->fullscreen || this->maximized) {
                return this->windowed_window_size;
            }
            return GetWindowSize(this->window);
        }

        // apply the windowed window size if fullscreen and maximized are disabled
        void Screen::ApplyWindowedSize() {
            if (!this->fullscreen && !this->maximized) {
                SDL_SetWindowSize(this->window, this->windowed_window_size.width,
                                  this->windowed_window_size.height);
            }
        }

        // set the window size to be applied when fullscreen is disabled
        void Screen::SetWindowSize(struct Size new_size) {
            // setting the window size during fullscreen is implementation defined,
            // so apply the resize only after fullscreen is disabled
            this->windowed_window_size = new_size;
            ApplyWindowedSize();
        }

        // get the preferred display bounds (i.e. the screen bounds with some margins)
        bool Screen::GetPreferredDisplayBounds(struct Size *bounds) {
            SDL_Rect rect;
# define GET_DISPLAY_BOUNDS(i, r) SDL_GetDisplayUsableBounds((i), (r))
            if (GET_DISPLAY_BOUNDS(0, &rect)) {
                LOGW("Could not get display usable bounds: %s", SDL_GetError());
                return false;
            }

            bounds->width = MAX(0, rect.w - DISPLAY_MARGINS);
            bounds->height = MAX(0, rect.h - DISPLAY_MARGINS);
            return true;
        }

        // return the optimal size of the window, with the following constraints:
        //  - it attempts to keep at least one dimension of the current_size (i.e. it
        //    crops the black borders)
        //  - it keeps the aspect ratio
        //  - it scales down to make it fit in the display_size
        struct Size Screen::GetOptimalSize(struct Size current_size,
                                           struct Size frame_size) {
            if (frame_size.width == 0 || frame_size.height == 0) {
                // avoid division by 0
                return current_size;
            }

            struct Size display_size{};
            // 32 bits because we need to multiply two 16 bits values
            uint32_t w;
            uint32_t h;

            if (!GetPreferredDisplayBounds(&display_size)) {
                // could not get display bounds, do not constraint the size
                w = current_size.width;
                h = current_size.height;
            } else {
                w = MIN(current_size.width, display_size.width);
                h = MIN(current_size.height, display_size.height);
            }

            bool keep_width = frame_size.width * h > frame_size.height * w;
            if (keep_width) {
                // remove black borders on top and bottom
                h = frame_size.height * w / frame_size.width;
            } else {
                // remove black borders on left and right (or none at all if it already
                // fits)
                w = frame_size.width * h / frame_size.height;
            }

            // w and h must fit into 16 bits
            assert(w < 0x10000 && h < 0x10000);
            return (struct Size) {(uint16_t) w, (uint16_t) h};
        }

        // same as get_optimal_size(), but read the current size from the window
        struct Size Screen::GetOptimalWindowSize(struct Size frame_size) {
            struct Size windowed_size = GetWindowedWindowSize();
            return GetOptimalSize(windowed_size, frame_size);
        }

        // initially, there is no current size, so use the frame size as current size
        // req_width and req_height, if not 0, are the sizes requested by the user
        struct Size Screen::GetInitialOptimalSize(struct Size frame_size, uint16_t req_width,
                                                  uint16_t req_height) {
            struct Size window_size{};
            if (!req_width && !req_height) {
                window_size = GetOptimalSize(frame_size, frame_size);
            } else {
                if (req_width) {
                    window_size.width = req_width;
                } else {
                    // compute from the requested height
                    window_size.width = (uint32_t) req_height * frame_size.width
                                        / frame_size.height;
                }
                if (req_height) {
                    window_size.height = req_height;
                } else {
                    // compute from the requested width
                    window_size.height = (uint32_t) req_width * frame_size.height
                                         / frame_size.width;
                }
            }
            return window_size;
        }

        void Screen::Init() {
            this->window = nullptr;
            this->renderer = nullptr;
            this->texture = nullptr;
            this->frame_size = {
                    .width=0,
                    .height=0
            };
            this->windowed_window_size = {
                    .width=0,
                    .height=0
            };
            this->windowed_window_size_backup = {
                    .width=0,
                    .height=0
            };
            this->has_frame = false;
            this->fullscreen = false;
            this->maximized = false;

        }


        bool Screen::InitRendering(const char *window_title,
                                   struct Size frame_size, bool always_on_top,
                                   int16_t window_x, int16_t window_y, uint16_t window_width,
                                   uint16_t window_height, uint16_t screen_width,
                                   uint16_t screen_height, bool window_borderless) {
            this->frame_size = frame_size;

            if (screen_width * screen_height != 0) {
                this->device_screen_size.width = screen_width;
                this->device_screen_size.height = screen_height;
            } else {
                this->device_screen_size = frame_size;
            }

            struct Size window_size =
                    GetInitialOptimalSize(frame_size, window_width, window_height);
            uint32_t window_flags = SDL_WINDOW_HIDDEN | SDL_WINDOW_RESIZABLE;

            window_flags |= SDL_WINDOW_ALLOW_HIGHDPI;

            if (always_on_top) {
                window_flags |= SDL_WINDOW_ALWAYS_ON_TOP;

            }
            if (window_borderless) {
                window_flags |= SDL_WINDOW_BORDERLESS;
            }

            int x = window_x != -1 ? window_x : (int) SDL_WINDOWPOS_UNDEFINED;
            int y = window_y != -1 ? window_y : (int) SDL_WINDOWPOS_UNDEFINED;
            this->window = SDL_CreateWindow(window_title, x, y,
                                            window_size.width, window_size.height,
                                            window_flags);
            if (!this->window) {
                LOGC("Could not create window: %s", SDL_GetError());
                return false;
            }

            this->renderer = SDL_CreateRenderer(this->window, -1,
                                                SDL_RENDERER_ACCELERATED);
            if (!this->renderer) {
                LOGC("Could not create renderer: %s", SDL_GetError());
                this->Destroy();
                return false;
            }

            if (SDL_RenderSetLogicalSize(this->renderer, frame_size.width,
                                         frame_size.height)) {
                LOGE("Could not set renderer logical size: %s", SDL_GetError());
                this->Destroy();
                return false;
            }


            LOGI("Initial texture: %"
                         PRIu16
                         "x%"
                         PRIu16, frame_size.width,
                 frame_size.height);
            this->texture = CreateTexture(this->renderer, frame_size);
            if (!this->texture) {
                LOGC("Could not create texture: %s", SDL_GetError());
                this->Destroy();
                return false;
            }

            this->windowed_window_size = window_size;

            return true;
        }

        void Screen::ShowWindow() {
            SDL_ShowWindow(this->window);
        }

        void Screen::Destroy() {
            if (this->texture) {
                SDL_DestroyTexture(this->texture);
            }
            if (this->renderer) {
                SDL_DestroyRenderer(this->renderer);
            }
            if (this->window) {
                SDL_DestroyWindow(this->window);
            }
        }

        // recreate the texture and resize the window if the frame size has changed
        bool Screen::PrepareForFrame(struct Size new_frame_size) {
            if (this->frame_size.width != new_frame_size.width
                || this->frame_size.height != new_frame_size.height) {
                if (SDL_RenderSetLogicalSize(this->renderer, new_frame_size.width,
                                             new_frame_size.height)) {
                    LOGE("Could not set renderer logical size: %s", SDL_GetError());
                    return false;
                }

                // frame dimension changed, destroy texture
                SDL_DestroyTexture(this->texture);

                struct Size windowed_size = GetWindowedWindowSize();
                struct Size target_size = {
                        (uint16_t) ((uint32_t) windowed_size.width * new_frame_size.width
                                    / this->frame_size.width),
                        (uint16_t) ((uint32_t) windowed_size.height * new_frame_size.height
                                    / this->frame_size.height),
                };
                target_size = GetOptimalSize(target_size, new_frame_size);
                SetWindowSize(target_size);

                this->frame_size = new_frame_size;

                LOGI("New texture: %"
                             PRIu16
                             "x%"
                             PRIu16,
                     this->frame_size.width, this->frame_size.height);
                this->texture = CreateTexture(this->renderer, new_frame_size);
                if (!this->texture) {
                    LOGC("Could not create texture: %s", SDL_GetError());
                    return false;
                }
            }

            return true;
        }

        // write the frame into the texture
        void Screen::UpdateTexture(const AVFrame *frame) {
            SDL_UpdateYUVTexture(this->texture, nullptr,
                                 frame->data[0], frame->linesize[0],
                                 frame->data[1], frame->linesize[1],
                                 frame->data[2], frame->linesize[2]);
        }

        bool Screen::UpdateFrame(video::VideoBuffer *vb) {
            util::mutex_lock(vb->mutex);
            const AVFrame *frame = vb->ConsumeRenderedFrame();
            struct Size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
            if (!PrepareForFrame(new_frame_size)) {
                util::mutex_unlock(vb->mutex);
                return false;
            }
            UpdateTexture(frame);
            util::mutex_unlock(vb->mutex);

            this->Render();
            return true;
        }

        void Screen::Render() {
            SDL_RenderClear(this->renderer);
            SDL_RenderCopy(this->renderer, this->texture,
                           nullptr, nullptr);
            SDL_RenderPresent(this->renderer);
        }

        void Screen::SwitchFullscreen() {
            uint32_t new_mode = this->fullscreen ? 0 : SDL_WINDOW_FULLSCREEN_DESKTOP;
            if (SDL_SetWindowFullscreen(this->window, new_mode)) {
                LOGW("Could not switch fullscreen mode: %s", SDL_GetError());
                return;
            }

            this->fullscreen = !this->fullscreen;
            ApplyWindowedSize();

            LOGD("Switched to %s mode", this->fullscreen ? "fullscreen" : "windowed");
            this->Render();
        }

        void Screen::ResizeToFit() {
            if (this->fullscreen) {
                return;
            }

            if (this->maximized) {
                SDL_RestoreWindow(this->window);
                this->maximized = false;
            }

            struct Size optimal_size =
                    GetOptimalWindowSize(this->frame_size);
            SDL_SetWindowSize(this->window, optimal_size.width, optimal_size.height);
            LOGD("Resized to optimal size");
        }

        void Screen::ResizeToPixelPerfect() {
            if (this->fullscreen) {
                return;
            }

            if (this->maximized) {
                SDL_RestoreWindow(this->window);
                this->maximized = false;
            }

            SDL_SetWindowSize(this->window, this->frame_size.width,
                              this->frame_size.height);
            LOGD("Resized to pixel-perfect");
        }

        void Screen::HandleWindowEvent(
                const SDL_WindowEvent *event) {
            switch (event->event) {
                case SDL_WINDOWEVENT_EXPOSED:
                    this->Render();
                    break;
                case SDL_WINDOWEVENT_SIZE_CHANGED:
                    if (!this->fullscreen && !this->maximized) {
                        // Backup the previous size: if we receive the MAXIMIZED event,
                        // then the new size must be ignored (it's the maximized size).
                        // We could not rely on the window flags due to race conditions
                        // (they could be updated asynchronously, at least on X11).
                        this->windowed_window_size_backup =
                                this->windowed_window_size;

                        // Save the windowed size, so that it is available once the
                        // window is maximized or fullscreen is enabled.
                        this->windowed_window_size = GetWindowSize(this->window);
                    }
                    this->Render();
                    break;
                case SDL_WINDOWEVENT_MAXIMIZED:
                    // The backup size must be non-nul.
                    assert(this->windowed_window_size_backup.width);
                    assert(this->windowed_window_size_backup.height);
                    // Revert the last size, it was updated while screen was maximized.
                    this->windowed_window_size = this->windowed_window_size_backup;
#ifndef NDEBUG
                    // Reset the backup to invalid values to detect unexpected usage
                    this->windowed_window_size_backup.width = 0;
                    this->windowed_window_size_backup.height = 0;
#endif
                    this->maximized = true;
                    break;
                case SDL_WINDOWEVENT_RESTORED:
                    this->maximized = false;
                    ApplyWindowedSize();
                    break;
            }
        }

        bool Screen::IsApk(const char *file) {
            const char *ext = strrchr(file, '.');
            return ext && !strcmp(ext, ".apk");
        }

        // init SDL and set appropriate hints
        bool Screen::InitSDLAndConfigure(bool display) {
            uint32_t flags = display ? SDL_INIT_VIDEO : SDL_INIT_EVENTS;
            if (SDL_Init(flags)) {
                LOGC("Could not initialize SDL: %s", SDL_GetError());
                return false;
            }

            atexit(SDL_Quit);

            if (!display) {
                return true;
            }

            // Use the best available scale quality
            if (!SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "2")) {
                LOGW("Could not enable bilinear filtering");
            }

            // Handle a click to gain focus as any other click
            if (!SDL_SetHint(SDL_HINT_MOUSE_FOCUS_CLICKTHROUGH, "1")) {
                LOGW("Could not enable mouse focus clickthrough");
            }

            // Disable compositor bypassing on X11
            if (!SDL_SetHint(SDL_HINT_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR, "0")) {
                LOGW("Could not disable X11 compositor bypass");
            }

            // Do not minimize on focus loss
            if (!SDL_SetHint(SDL_HINT_VIDEO_MINIMIZE_ON_FOCUS_LOSS, "0")) {
                LOGW("Could not disable minimize on focus loss");
            }

            // Do not disable the screensaver when scrcpy is running
            SDL_EnableScreenSaver();
            return true;
        }

#if defined(__APPLE__) || defined(__WINDOWS__)
# define CONTINUOUS_RESIZING_WORKAROUND
#endif

#ifdef CONTINUOUS_RESIZING_WORKAROUND

// On Windows and MacOS, resizing blocks the event loop, so resizing events are
// not triggered. As a workaround, handle them in an event handler.
//
// <https://bugzilla.libsdl.org/show_bug.cgi?id=2077>
// <https://stackoverflow.com/a/40693139/1987178>
        int Screen::EventWatcher(void *data, SDL_Event *event) {
            (void) data;
            if (event->type == SDL_WINDOWEVENT
                && event->window.event == SDL_WINDOWEVENT_RESIZED) {
                // called from another thread, not very safe, but it's a workaround!
                screen.Render();
            }
            return 0;
        }

#endif


        enum EventResult Screen::HandleEvent(SDL_Event *event, bool control) {
            switch (event->type) {
                case EVENT_STREAM_STOPPED:
                    LOGD("Video stream stopped");
                    return EVENT_RESULT_STOPPED_BY_EOS;
                case SDL_QUIT:
                    LOGD("User requested to quit");
                    return EVENT_RESULT_STOPPED_BY_USER;
                case EVENT_NEW_FRAME:
                    if (!screen.has_frame) {
                        screen.has_frame = true;
                        // this is the very first frame, show the window
                        screen.ShowWindow();
                    }
                    if (!screen.UpdateFrame(&video_buffer)) {
                        return EVENT_RESULT_CONTINUE;
                    }
                    break;
                case SDL_WINDOWEVENT:
                    screen.HandleWindowEvent(&event->window);
                    break;
                case SDL_TEXTINPUT:
                    if (!control) {
                        break;
                    }
                    input_manager.ProcessTextInput(&event->text);
                    break;
                case SDL_KEYDOWN:
                case SDL_KEYUP:
                    // some key events do not interact with the device, so process the
                    // event even if control is disabled
                    input_manager.ProcessKey(&event->key, control);
                    break;
                case SDL_MOUSEMOTION:
                    if (!control) {
                        break;
                    }
                    input_manager.ProcessMouseMotion(&event->motion);
                    break;
                case SDL_MOUSEWHEEL:
                    if (!control) {
                        break;
                    }
                    input_manager.ProcessMouseWheel(&event->wheel);
                    break;
                case SDL_MOUSEBUTTONDOWN:
                case SDL_MOUSEBUTTONUP:
                    // some mouse events do not interact with the device, so process
                    // the event even if control is disabled
                    input_manager.ProcessMouseButton(&event->button,
                                                     control);
                    break;
                case SDL_FINGERMOTION:
                case SDL_FINGERDOWN:
                case SDL_FINGERUP:
                    input_manager.ProcessTouch(&event->tfinger);
                    break;
                case SDL_DROPFILE: {
                    if (!control) {
                        break;
                    }
                    FileHandlerActionType action;
                    if (IsApk(event->drop.file)) {
                        action = ACTION_INSTALL_APK;
                    } else {
                        action = ACTION_PUSH_FILE;
                    }
                    file_handler.Request(action, event->drop.file);
                    break;
                }
            }
            return EVENT_RESULT_CONTINUE;
        }

        bool Screen::EventLoop(bool display, bool control) {
            (void) display;
#ifdef CONTINUOUS_RESIZING_WORKAROUND
            if (display) {
                SDL_AddEventWatch(EventWatcher, nullptr);
            }
#endif
            SDL_Event event;
            while (SDL_WaitEvent(&event)) {
                enum EventResult result = HandleEvent(&event, control);
                switch (result) {
                    case EVENT_RESULT_STOPPED_BY_USER:
                        return true;
                    case EVENT_RESULT_STOPPED_BY_EOS:
                        LOGW("Device disconnected");
                        return false;
                    case EVENT_RESULT_CONTINUE:
                        break;
                }
            }
            return false;
        }

    }
}