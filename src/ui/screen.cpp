//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "screen.hpp"

#include <cassert>
#include <SDL2/SDL.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>

#include "config.hpp"
#include "common.hpp"
#include "compat.hpp"
#include "icon.xpm"
#include "tiny_xpm.hpp"
#include "video/video_buffer.hpp"
#include "util/lock.hpp"
#include "util/log.hpp"


#define DISPLAY_MARGINS 96

// get the window size in a struct size
static struct size
get_window_size(SDL_Window *window) {
    int width;
    int height;
    SDL_GetWindowSize(window, &width, &height);

    struct size size;
    size.width = width;
    size.height = height;
    return size;
}

// get the windowed window size
static struct size
get_windowed_window_size(const struct screen *screen) {
    if (screen->fullscreen || screen->maximized) {
        return screen->windowed_window_size;
    }
    return get_window_size(screen->window);
}

// apply the windowed window size if fullscreen and maximized are disabled
static void
apply_windowed_size(struct screen *screen) {
    if (!screen->fullscreen && !screen->maximized) {
        SDL_SetWindowSize(screen->window, screen->windowed_window_size.width,
                          screen->windowed_window_size.height);
    }
}

// set the window size to be applied when fullscreen is disabled
static void
set_window_size(struct screen *screen, struct size new_size) {
    // setting the window size during fullscreen is implementation defined,
    // so apply the resize only after fullscreen is disabled
    screen->windowed_window_size = new_size;
    apply_windowed_size(screen);
}

// get the preferred display bounds (i.e. the screen bounds with some margins)
static bool
get_preferred_display_bounds(struct size *bounds) {
    SDL_Rect rect;
#ifdef SCRCPY_SDL_HAS_GET_DISPLAY_USABLE_BOUNDS
# define GET_DISPLAY_BOUNDS(i, r) SDL_GetDisplayUsableBounds((i), (r))
#else
# define GET_DISPLAY_BOUNDS(i, r) SDL_GetDisplayBounds((i), (r))
#endif
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
static struct size
get_optimal_size(struct size current_size, struct size frame_size) {
    if (frame_size.width == 0 || frame_size.height == 0) {
        // avoid division by 0
        return current_size;
    }

    struct size display_size;
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
    return (struct size) {(uint16_t) w, (uint16_t) h};
}

// same as get_optimal_size(), but read the current size from the window
static inline struct size
get_optimal_window_size(const struct screen *screen, struct size frame_size) {
    struct size windowed_size = get_windowed_window_size(screen);
    return get_optimal_size(windowed_size, frame_size);
}

// initially, there is no current size, so use the frame size as current size
// req_width and req_height, if not 0, are the sizes requested by the user
static inline struct size
get_initial_optimal_size(struct size frame_size, uint16_t req_width,
                         uint16_t req_height) {
    struct size window_size;
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

void
screen_init(struct screen *screen) {
    *screen = (struct screen) SCREEN_INITIALIZER;
}

static inline SDL_Texture *
create_texture(SDL_Renderer *renderer, struct size frame_size) {
    return SDL_CreateTexture(renderer, SDL_PIXELFORMAT_YV12,
                             SDL_TEXTUREACCESS_STREAMING,
                             frame_size.width, frame_size.height);
}

bool
screen_init_rendering(struct screen *screen, const char *window_title,
                      struct size frame_size, bool always_on_top,
                      int16_t window_x, int16_t window_y, uint16_t window_width,
                      uint16_t window_height, uint16_t screen_width,
                      uint16_t screen_height, bool window_borderless) {
    screen->frame_size = frame_size;

    if (screen_width * screen_height != 0) {
        screen->device_screen_size.width = screen_width;
        screen->device_screen_size.height = screen_height;
    } else {
        screen->device_screen_size = frame_size;
    }

    struct size window_size =
            get_initial_optimal_size(frame_size, window_width, window_height);
    uint32_t window_flags = SDL_WINDOW_HIDDEN | SDL_WINDOW_RESIZABLE;
#ifdef HIDPI_SUPPORT
    window_flags |= SDL_WINDOW_ALLOW_HIGHDPI;
#endif
    if (always_on_top) {
#ifdef SCRCPY_SDL_HAS_WINDOW_ALWAYS_ON_TOP
        window_flags |= SDL_WINDOW_ALWAYS_ON_TOP;
#else
        LOGW("The 'always on top' flag is not available "
             "(compile with SDL >= 2.0.5 to enable it)");
#endif
    }
    if (window_borderless) {
        window_flags |= SDL_WINDOW_BORDERLESS;
    }

    int x = window_x != -1 ? window_x : (int) SDL_WINDOWPOS_UNDEFINED;
    int y = window_y != -1 ? window_y : (int) SDL_WINDOWPOS_UNDEFINED;
    screen->window = SDL_CreateWindow(window_title, x, y,
                                      window_size.width, window_size.height,
                                      window_flags);
    if (!screen->window) {
        LOGC("Could not create window: %s", SDL_GetError());
        return false;
    }

    screen->renderer = SDL_CreateRenderer(screen->window, -1,
                                          SDL_RENDERER_ACCELERATED);
    if (!screen->renderer) {
        LOGC("Could not create renderer: %s", SDL_GetError());
        screen_destroy(screen);
        return false;
    }

    if (SDL_RenderSetLogicalSize(screen->renderer, frame_size.width,
                                 frame_size.height)) {
        LOGE("Could not set renderer logical size: %s", SDL_GetError());
        screen_destroy(screen);
        return false;
    }

    SDL_Surface *icon = read_xpm(icon_xpm);
    if (icon) {
        SDL_SetWindowIcon(screen->window, icon);
        SDL_FreeSurface(icon);
    } else {
        LOGW("Could not load icon");
    }

    LOGI("Initial texture: %"
                 PRIu16
                 "x%"
                 PRIu16, frame_size.width,
         frame_size.height);
    screen->texture = create_texture(screen->renderer, frame_size);
    if (!screen->texture) {
        LOGC("Could not create texture: %s", SDL_GetError());
        screen_destroy(screen);
        return false;
    }

    screen->windowed_window_size = window_size;

    return true;
}

void
screen_show_window(struct screen *screen) {
    SDL_ShowWindow(screen->window);
}

void
screen_destroy(struct screen *screen) {
    if (screen->texture) {
        SDL_DestroyTexture(screen->texture);
    }
    if (screen->renderer) {
        SDL_DestroyRenderer(screen->renderer);
    }
    if (screen->window) {
        SDL_DestroyWindow(screen->window);
    }
}

// recreate the texture and resize the window if the frame size has changed
static bool
prepare_for_frame(struct screen *screen, struct size new_frame_size) {
    if (screen->frame_size.width != new_frame_size.width
        || screen->frame_size.height != new_frame_size.height) {
        if (SDL_RenderSetLogicalSize(screen->renderer, new_frame_size.width,
                                     new_frame_size.height)) {
            LOGE("Could not set renderer logical size: %s", SDL_GetError());
            return false;
        }

        // frame dimension changed, destroy texture
        SDL_DestroyTexture(screen->texture);

        struct size windowed_size = get_windowed_window_size(screen);
        struct size target_size = {
                (uint16_t) ((uint32_t) windowed_size.width * new_frame_size.width
                            / screen->frame_size.width),
                (uint16_t) ((uint32_t) windowed_size.height * new_frame_size.height
                            / screen->frame_size.height),
        };
        target_size = get_optimal_size(target_size, new_frame_size);
        set_window_size(screen, target_size);

        screen->frame_size = new_frame_size;

        LOGI("New texture: %"
                     PRIu16
                     "x%"
                     PRIu16,
             screen->frame_size.width, screen->frame_size.height);
        screen->texture = create_texture(screen->renderer, new_frame_size);
        if (!screen->texture) {
            LOGC("Could not create texture: %s", SDL_GetError());
            return false;
        }
    }

    return true;
}

// write the frame into the texture
static void
update_texture(struct screen *screen, const AVFrame *frame) {
    SDL_UpdateYUVTexture(screen->texture, NULL,
                         frame->data[0], frame->linesize[0],
                         frame->data[1], frame->linesize[1],
                         frame->data[2], frame->linesize[2]);

    screen_saveframe(screen, (AVFrame *) frame);

    AVCodecContext *pCodecCtxOrig = screen->stream.codec_ctx;



//    write_frame_to_file(frame,screen->stream.codec_ctx);

}

bool
screen_update_frame(struct screen *screen, struct video_buffer *vb) {
    mutex_lock(vb->mutex);
    const AVFrame *frame = video_buffer_consume_rendered_frame(vb);
    struct size new_frame_size = {(uint16_t) frame->width, (uint16_t) frame->height};
    if (!prepare_for_frame(screen, new_frame_size)) {
        mutex_unlock(vb->mutex);
        return false;
    }
    update_texture(screen, frame);
    mutex_unlock(vb->mutex);

    screen_render(screen);
    return true;
}


void save_texture(struct screen *screen, SDL_Renderer *renderer, SDL_Texture *texture, const char *file_name) {
    SDL_Texture *target = SDL_GetRenderTarget(renderer);
    SDL_SetRenderTarget(renderer, texture);
    int width, height, format;
    SDL_QueryTexture(texture, reinterpret_cast<Uint32 *>(&format), NULL, &width, &height);
    bool is_portrait = height > width;
    uint16_t screen_width = screen->device_screen_size.width;
    uint16_t screen_height = screen->device_screen_size.height;
    if (!is_portrait) {
        screen_width = screen->device_screen_size.height;
        screen_height = screen->device_screen_size.width;
    }
    LOGI("Capture screen size: %"
                 PRIu16
                 "x%"
                 PRIu16, screen_width,
         screen_height);
    SDL_Surface *surface = SDL_CreateRGBSurface(0, screen_width,
                                                screen_height, 32, 0, 0, 0, 0);
    SDL_RenderReadPixels(renderer, NULL, surface->format->format, surface->pixels, surface->pitch);

    SDL_SaveBMP(surface, file_name);
    SDL_FreeSurface(surface);

    SDL_SetRenderTarget(renderer, target);
}

void
screen_render(struct screen *screen) {

    SDL_RenderClear(screen->renderer);
    SDL_RenderCopy(screen->renderer, screen->texture, NULL, NULL);
    SDL_RenderPresent(screen->renderer);


}

void screen_capture(struct screen *screen) {
    save_texture(screen, screen->renderer, screen->texture, "capture.bmp");
}


void
screen_switch_fullscreen(struct screen *screen) {
    uint32_t new_mode = screen->fullscreen ? 0 : SDL_WINDOW_FULLSCREEN_DESKTOP;
    if (SDL_SetWindowFullscreen(screen->window, new_mode)) {
        LOGW("Could not switch fullscreen mode: %s", SDL_GetError());
        return;
    }

    screen->fullscreen = !screen->fullscreen;
    apply_windowed_size(screen);

    LOGD("Switched to %s mode", screen->fullscreen ? "fullscreen" : "windowed");
    screen_render(screen);
}

void
screen_resize_to_fit(struct screen *screen) {
    if (screen->fullscreen) {
        return;
    }

    if (screen->maximized) {
        SDL_RestoreWindow(screen->window);
        screen->maximized = false;
    }

    struct size optimal_size =
            get_optimal_window_size(screen, screen->frame_size);
    SDL_SetWindowSize(screen->window, optimal_size.width, optimal_size.height);
    LOGD("Resized to optimal size");
}

void
screen_resize_to_pixel_perfect(struct screen *screen) {
    if (screen->fullscreen) {
        return;
    }

    if (screen->maximized) {
        SDL_RestoreWindow(screen->window);
        screen->maximized = false;
    }

    SDL_SetWindowSize(screen->window, screen->frame_size.width,
                      screen->frame_size.height);
    LOGD("Resized to pixel-perfect");
}

void
screen_handle_window_event(struct screen *screen,
                           const SDL_WindowEvent *event) {
    switch (event->event) {
        case SDL_WINDOWEVENT_EXPOSED:
            screen_render(screen);
            break;
        case SDL_WINDOWEVENT_SIZE_CHANGED:
            if (!screen->fullscreen && !screen->maximized) {
                // Backup the previous size: if we receive the MAXIMIZED event,
                // then the new size must be ignored (it's the maximized size).
                // We could not rely on the window flags due to race conditions
                // (they could be updated asynchronously, at least on X11).
                screen->windowed_window_size_backup =
                        screen->windowed_window_size;

                // Save the windowed size, so that it is available once the
                // window is maximized or fullscreen is enabled.
                screen->windowed_window_size = get_window_size(screen->window);
            }
            screen_render(screen);
            break;
        case SDL_WINDOWEVENT_MAXIMIZED:
            // The backup size must be non-nul.
            assert(screen->windowed_window_size_backup.width);
            assert(screen->windowed_window_size_backup.height);
            // Revert the last size, it was updated while screen was maximized.
            screen->windowed_window_size = screen->windowed_window_size_backup;
#ifdef DEBUG
        // Reset the backup to invalid values to detect unexpected usage
        screen->windowed_window_size_backup.width = 0;
        screen->windowed_window_size_backup.height = 0;
#endif
            screen->maximized = true;
            break;
        case SDL_WINDOWEVENT_RESTORED:
            screen->maximized = false;
            apply_windowed_size(screen);
            break;
    }
}


void SaveFrame(AVFrame *pFrame, int width, int height, int iFrame) {
    FILE *pFile;
    char szFilename[32];
    int y;

    // Open file
    sprintf(szFilename, "frame%d.ppm", iFrame);
    pFile = fopen(szFilename, "wb");
    if (pFile == NULL)
        return;

    // Write header
    fprintf(pFile, "P6\n%d %d\n255\n", width, height);

    // Write pixel data
    for (y = 0; y < height; y++)
        fwrite(pFrame->data[0] + y * pFrame->linesize[0], 1, width * 3, pFile);

    // Close file
    fclose(pFile);
}

void screen_saveframe(struct screen *screen, AVFrame *pFrame) {
    AVCodecContext *pCodecCtxOrig = NULL;
    AVCodecContext *pCodecCtx = NULL;
    AVCodec *pCodec = NULL;

    SDL_Texture *texture;

    AVFrame *pFrameRGB = NULL;
    struct SwsContext *sws_ctx = NULL;

    int numBytes;
    uint8_t *buffer = NULL;

    pCodecCtxOrig = screen->stream.codec_ctx;
    pCodec = screen->stream.codec;
    texture = screen->texture;
    int width, height, format;
    SDL_QueryTexture(texture, (Uint32 *) (&format), NULL, &width, &height);

    if (pCodec == NULL) {
        fprintf(stderr, "Unsupported codec!\n");
        return;
    }

    // Copy context
    pCodecCtx = avcodec_alloc_context3(pCodec);
    if (avcodec_copy_context(pCodecCtx, pCodecCtxOrig) != 0) {
        fprintf(stderr, "Couldn't copy codec context");
        return; // Error copying codec context
    }

    pCodecCtx->height = height;
    pCodecCtx->width = width;
    pCodecCtx->pix_fmt = AV_PIX_FMT_YUV420P;
    pCodecCtx->coded_height = height;
    pCodecCtx->coded_width = width;

    // Open codec
    if (avcodec_open2(pCodecCtx, pCodec, NULL) < 0)
        return; // Could not open codec

    pFrameRGB = av_frame_alloc();
    if (pFrameRGB == NULL)
        return;

    // Determine required buffer size and allocate buffer
    numBytes = avpicture_get_size(AV_PIX_FMT_RGB24, pCodecCtx->width,
                                  pCodecCtx->height);
    buffer = (uint8_t *) av_malloc(numBytes * sizeof(uint8_t));

    // Assign appropriate parts of buffer to image planes in pFrameRGB
    // Note that pFrameRGB is an AVFrame, but AVFrame is a superset
    // of AVPicture
    avpicture_fill((AVPicture *) pFrameRGB, buffer, AV_PIX_FMT_RGB24,
                   pCodecCtx->width, pCodecCtx->height);

    // initialize SWS context for software scaling
    sws_ctx = sws_getContext(pCodecCtx->width,
                             pCodecCtx->height,
                             pCodecCtx->pix_fmt,
                             pCodecCtx->width,
                             pCodecCtx->height,
                             AV_PIX_FMT_RGB24,
                             SWS_BILINEAR,
                             NULL,
                             NULL,
                             NULL
    );

    if (sws_ctx == NULL) return;
    sws_scale(sws_ctx, (uint8_t const *const *) pFrame->data,
              pFrame->linesize, 0, pCodecCtx->height,
              pFrameRGB->data, pFrameRGB->linesize);


    SaveFrame(pFrameRGB, pCodecCtx->width, pCodecCtx->height,
              0);

    av_free(buffer);

    av_frame_free(&pFrameRGB);



    // Close the codecs
    avcodec_close(pCodecCtx);
}

