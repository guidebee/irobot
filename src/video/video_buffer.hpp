//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_VIDEO_BUFFER_HPP
#define ANDROID_IROBOT_VIDEO_BUFFER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <libavutil/avutil.h>
#include <libavformat/avformat.h>

#if defined (__cplusplus)
}
#endif

#include <SDL2/SDL_mutex.h>

#include "config.hpp"

#include "fps_counter.hpp"

namespace irobot::video {
    // forward declarations
    typedef struct AVFrame AVFrame;

    class VideoBuffer {
    public:
        AVFrame *decoding_frame;
        AVFrame *rendering_frame;
        SDL_mutex *mutex;
        bool render_expired_frames;
        bool interrupted;
        SDL_cond *rendering_frame_consumed_cond;
        bool rendering_frame_consumed;
        struct FpsCounter *fps_counter;
        int frame_number;

        AVFrame *rgb_frame;
        uint8_t *buffer;

        bool Init(struct FpsCounter *fps_counter,
                  bool render_expired_frames);

        void Destroy();


        // set the decoded frame as ready for rendering
        // this function locks frames->mutex during its execution
        // the output flag is set to report whether the previous frame has been skipped
        void OfferDecodedFrame(bool *previous_frame_skipped);

        // mark the rendering frame as consumed and return it
        // MUST be called with frames->mutex locked!!!
        // the caller is expected to render the returned frame to some texture before
        // unlocking frames->mutex
        const AVFrame *ConsumeRenderedFrame();

        // wake up and avoid any blocking call
        void Interrupt();

    private:
        void SwapFrames();

    };

}
#endif //ANDROID_IROBOT_VIDEO_BUFFER_HPP
