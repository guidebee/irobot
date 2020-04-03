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

struct VideoBuffer;

class Screen {
public:
    SDL_Window *window;
    SDL_Renderer *renderer;
    SDL_Texture *texture;
    struct size frame_size;
    // The window size the last time it was not maximized or fullscreen.
    struct size windowed_window_size;
    // Since we receive the event SIZE_CHANGED before MAXIMIZED, we must be
    // able to revert the size to its non-maximized value.
    struct size windowed_window_size_backup;
    bool has_frame;
    bool fullscreen;
    bool maximized;
    bool no_window;

    struct size device_screen_size;


    // initialize default values
    void init();

    // initialize screen, create window, renderer and texture (window is hidden)
    bool init_rendering(const char *window_title,
                        struct size frame_size, bool always_on_top,
                        int16_t window_x, int16_t window_y, uint16_t window_width,
                        uint16_t window_height, uint16_t screen_width,
                        uint16_t screen_height, bool window_borderless);

    // show the window
    void show_window();

    // destroy window, renderer and texture (if any)
    void destroy();

    // resize if necessary and write the rendered frame into the texture
    bool update_frame(struct VideoBuffer *vb);

    // render the texture to the renderer
    void render();

    // switch the fullscreen mode
    void switch_fullscreen();

    // resize window to optimal size (remove black borders)
    void resize_to_fit();

    // resize window to 1:1 (pixel-perfect)
    void resize_to_pixel_perfect();

    // react to window events
    void handle_window_event(const SDL_WindowEvent *event);


};


#endif //ANDROID_IROBOT_SCREEN_HPP
