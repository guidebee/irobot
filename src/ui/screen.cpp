//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "screen.hpp"

#include <cassert>

#include "common.hpp"

#include "video/video_buffer.hpp"
#include "util/lock.hpp"

#include "util/log.hpp"

#include "ui/events.hpp"
#include "ui/input_manager.hpp"
#include "android/file_handler.hpp"

extern Screen screen;
extern InputManager input_manager;
extern VideoBuffer video_buffer;
extern Controller controller;
extern FileHandler file_handler;


#define DISPLAY_MARGINS 96

// get the window size in a struct size
struct Size Screen::get_window_size(SDL_Window *window) {
    int width;
    int height;
    SDL_GetWindowSize(window, &width, &height);

    struct Size size{};
    size.width = width;
    size.height = height;
    return size;
}

// get the windowed window size
struct Size Screen::get_windowed_window_size() {
    if (this->fullscreen || this->maximized) {
        return this->windowed_window_size;
    }
    return get_window_size(this->window);
}

// apply the windowed window size if fullscreen and maximized are disabled
void Screen::apply_windowed_size() {
    if (!this->fullscreen && !this->maximized) {
        SDL_SetWindowSize(this->window, this->windowed_window_size.width,
                          this->windowed_window_size.height);
    }
}

// set the window size to be applied when fullscreen is disabled
void Screen::set_window_size(struct Size new_size) {
    // setting the window size during fullscreen is implementation defined,
    // so apply the resize only after fullscreen is disabled
    this->windowed_window_size = new_size;
    apply_windowed_size();
}

// get the preferred display bounds (i.e. the screen bounds with some margins)
bool Screen::get_preferred_display_bounds(struct Size *bounds) {
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
struct Size Screen::get_optimal_size(struct Size current_size,
                                     struct Size frame_size) {
    if (frame_size.width == 0 || frame_size.height == 0) {
        // avoid division by 0
        return current_size;
    }

    struct Size display_size{};
    // 32 bits because we need to multiply two 16 bits values
    uint32_t w;
    uint32_t h;

    if (!get_preferred_display_bounds(&display_size)) {
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
struct Size Screen::get_optimal_window_size(struct Size frame_size) {
    struct Size windowed_size = get_windowed_window_size();
    return get_optimal_size(windowed_size, frame_size);
}

// initially, there is no current size, so use the frame size as current size
// req_width and req_height, if not 0, are the sizes requested by the user
struct Size Screen::get_initial_optimal_size(struct Size frame_size, uint16_t req_width,
                                             uint16_t req_height) {
    struct Size window_size{};
    if (!req_width && !req_height) {
        window_size = get_optimal_size(frame_size, frame_size);
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

void Screen::init() {
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


bool Screen::init_rendering(const char *window_title,
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
            get_initial_optimal_size(frame_size, window_width, window_height);
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
        this->destroy();
        return false;
    }

    if (SDL_RenderSetLogicalSize(this->renderer, frame_size.width,
                                 frame_size.height)) {
        LOGE("Could not set renderer logical size: %s", SDL_GetError());
        this->destroy();
        return false;
    }


    LOGI("Initial texture: %"
                 PRIu16
                 "x%"
                 PRIu16, frame_size.width,
         frame_size.height);
    this->texture = create_texture(this->renderer, frame_size);
    if (!this->texture) {
        LOGC("Could not create texture: %s", SDL_GetError());
        this->destroy();
        return false;
    }

    this->windowed_window_size = window_size;

    return true;
}

void Screen::show_window() {
    SDL_ShowWindow(this->window);
}

void Screen::destroy() {
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
bool Screen::prepare_for_frame(struct Size new_frame_size) {
    if (this->frame_size.width != new_frame_size.width
        || this->frame_size.height != new_frame_size.height) {
        if (SDL_RenderSetLogicalSize(this->renderer, new_frame_size.width,
                                     new_frame_size.height)) {
            LOGE("Could not set renderer logical size: %s", SDL_GetError());
            return false;
        }

        // frame dimension changed, destroy texture
        SDL_DestroyTexture(this->texture);

        struct Size windowed_size = get_windowed_window_size();
        struct Size target_size = {
                (uint16_t) ((uint32_t) windowed_size.width * new_frame_size.width
                            / this->frame_size.width),
                (uint16_t) ((uint32_t) windowed_size.height * new_frame_size.height
                            / this->frame_size.height),
        };
        target_size = get_optimal_size(target_size, new_frame_size);
        set_window_size(target_size);

        this->frame_size = new_frame_size;

        LOGI("New texture: %"
                     PRIu16
                     "x%"
                     PRIu16,
             this->frame_size.width, this->frame_size.height);
        this->texture = create_texture(this->renderer, new_frame_size);
        if (!this->texture) {
            LOGC("Could not create texture: %s", SDL_GetError());
            return false;
        }
    }

    return true;
}

// write the frame into the texture
void Screen::update_texture(const AVFrame *frame) {
    SDL_UpdateYUVTexture(this->texture, nullptr,
                         frame->data[0], frame->linesize[0],
                         frame->data[1], frame->linesize[1],
                         frame->data[2], frame->linesize[2]);
}

bool Screen::update_frame(VideoBuffer *vb) {
    mutex_lock(vb->mutex);
    const AVFrame *frame = vb->consume_rendered_frame();
    struct Size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
    if (!prepare_for_frame(new_frame_size)) {
        mutex_unlock(vb->mutex);
        return false;
    }
    update_texture(frame);
    mutex_unlock(vb->mutex);

    this->render();
    return true;
}

void Screen::render() {
    SDL_RenderClear(this->renderer);
    SDL_RenderCopy(this->renderer, this->texture,
                   nullptr, nullptr);
    SDL_RenderPresent(this->renderer);
}

void Screen::switch_fullscreen() {
    uint32_t new_mode = this->fullscreen ? 0 : SDL_WINDOW_FULLSCREEN_DESKTOP;
    if (SDL_SetWindowFullscreen(this->window, new_mode)) {
        LOGW("Could not switch fullscreen mode: %s", SDL_GetError());
        return;
    }

    this->fullscreen = !this->fullscreen;
    apply_windowed_size();

    LOGD("Switched to %s mode", this->fullscreen ? "fullscreen" : "windowed");
    this->render();
}

void Screen::resize_to_fit() {
    if (this->fullscreen) {
        return;
    }

    if (this->maximized) {
        SDL_RestoreWindow(this->window);
        this->maximized = false;
    }

    struct Size optimal_size =
            get_optimal_window_size(this->frame_size);
    SDL_SetWindowSize(this->window, optimal_size.width, optimal_size.height);
    LOGD("Resized to optimal size");
}

void Screen::resize_to_pixel_perfect() {
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

void Screen::handle_window_event(
        const SDL_WindowEvent *event) {
    switch (event->event) {
        case SDL_WINDOWEVENT_EXPOSED:
            this->render();
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
                this->windowed_window_size = get_window_size(this->window);
            }
            this->render();
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
            apply_windowed_size();
            break;
    }
}


static bool is_apk(const char *file) {
    const char *ext = strrchr(file, '.');
    return ext && !strcmp(ext, ".apk");
}

// init SDL and set appropriate hints
bool Screen::sdl_init_and_configure(bool display) {
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
int Screen::event_watcher(void *data, SDL_Event *event) {
    (void) data;
    if (event->type == SDL_WINDOWEVENT
        && event->window.event == SDL_WINDOWEVENT_RESIZED) {
        // called from another thread, not very safe, but it's a workaround!
        screen.render();
    }
    return 0;
}

#endif


enum EventResult Screen::handle_event(SDL_Event *event, bool control) {
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
                screen.show_window();
            }
            if (!screen.update_frame(&video_buffer)) {
                return EVENT_RESULT_CONTINUE;
            }
            break;
        case SDL_WINDOWEVENT:
            screen.handle_window_event(&event->window);
            break;
        case SDL_TEXTINPUT:
            if (!control) {
                break;
            }
            input_manager.process_text_input(&event->text);
            break;
        case SDL_KEYDOWN:
        case SDL_KEYUP:
            // some key events do not interact with the device, so process the
            // event even if control is disabled
            input_manager.process_key(&event->key, control);
            break;
        case SDL_MOUSEMOTION:
            if (!control) {
                break;
            }
            input_manager.process_mouse_motion(&event->motion);
            break;
        case SDL_MOUSEWHEEL:
            if (!control) {
                break;
            }
            input_manager.process_mouse_wheel(&event->wheel);
            break;
        case SDL_MOUSEBUTTONDOWN:
        case SDL_MOUSEBUTTONUP:
            // some mouse events do not interact with the device, so process
            // the event even if control is disabled
            input_manager.process_mouse_button(&event->button,
                                               control);
            break;
        case SDL_FINGERMOTION:
        case SDL_FINGERDOWN:
        case SDL_FINGERUP:
            input_manager.process_touch(&event->tfinger);
            break;
        case SDL_DROPFILE: {
            if (!control) {
                break;
            }
            FileHandlerActionType action;
            if (is_apk(event->drop.file)) {
                action = ACTION_INSTALL_APK;
            } else {
                action = ACTION_PUSH_FILE;
            }
            file_handler.request(action, event->drop.file);
            break;
        }
    }
    return EVENT_RESULT_CONTINUE;
}

bool Screen::event_loop(bool display, bool control) {
    (void) display;
#ifdef CONTINUOUS_RESIZING_WORKAROUND
    if (display) {
        SDL_AddEventWatch(event_watcher, nullptr);
    }
#endif
    SDL_Event event;
    while (SDL_WaitEvent(&event)) {
        enum EventResult result = handle_event(&event, control);
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

