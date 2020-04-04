//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_SCREEN_HPP
#define ANDROID_IROBOT_SCREEN_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "common.hpp"
#include "video/stream.hpp"

namespace irobot::ui {

    enum EventResult {
        EVENT_RESULT_CONTINUE,
        EVENT_RESULT_STOPPED_BY_USER,
        EVENT_RESULT_STOPPED_BY_EOS,
    };


    class Screen {
    public:
        SDL_Window *window;
        SDL_Renderer *renderer;
        SDL_Texture *texture;
        struct Size frame_size;
        // The window size the last time it was not maximized or fullscreen.
        struct Size windowed_window_size;
        // Since we receive the event SIZE_CHANGED before MAXIMIZED, we must be
        // able to revert the size to its non-maximized value.
        struct Size windowed_window_size_backup;
        bool has_frame;
        bool fullscreen;
        bool maximized;

        struct Size device_screen_size;

        // initialize default values
        void Init();

        // initialize screen, create window, renderer and texture (window is hidden)
        bool InitRendering(const char *window_title,
                           struct Size frame_size, bool always_on_top,
                           int16_t window_x, int16_t window_y, uint16_t window_width,
                           uint16_t window_height, uint16_t screen_width,
                           uint16_t screen_height, bool window_borderless);

        // show the window
        void ShowWindow();

        // destroy window, renderer and texture (if any)
        void Destroy();

        // resize if necessary and write the rendered frame into the texture
        bool UpdateFrame(video::VideoBuffer *vb);

        // render the texture to the renderer
        void Render();

        // switch the fullscreen mode
        void SwitchFullscreen();

        // resize window to optimal size (remove black borders)
        void ResizeToFit();

        // resize window to 1:1 (pixel-perfect)
        void ResizeToPixelPerfect();

        // react to window events
        void HandleWindowEvent(const SDL_WindowEvent *event);

        static struct Size GetWindowSize(SDL_Window *window);

        static bool GetPreferredDisplayBounds(struct Size *bounds);

        static struct Size GetOptimalSize(struct Size current_size,
                                          struct Size frame_size);

        static struct Size GetInitialOptimalSize(struct Size frame_size,
                                                 uint16_t req_width,
                                                 uint16_t req_height);

        static inline SDL_Texture *CreateTexture(SDL_Renderer *renderer,
                                                 struct Size frame_size) {
            return SDL_CreateTexture(renderer, SDL_PIXELFORMAT_YV12,
                                     SDL_TEXTUREACCESS_STREAMING,
                                     frame_size.width, frame_size.height);
        }

        static bool InitSDLAndConfigure(bool display);

        static int EventWatcher(void *data, SDL_Event *event);

        static bool EventLoop(bool display, bool control);

        static enum EventResult HandleEvent(SDL_Event *event, bool control);

        static bool IsApk(const char *file);

    private:
        struct Size GetWindowedWindowSize();

        void ApplyWindowedSize();

        void SetWindowSize(struct Size new_size);

        struct Size GetOptimalWindowSize(struct Size frame_size);

        bool PrepareForFrame(struct Size new_frame_size);

        void UpdateTexture(const AVFrame *frame);


    };

}

#endif //ANDROID_IROBOT_SCREEN_HPP
