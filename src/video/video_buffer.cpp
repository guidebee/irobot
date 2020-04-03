//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "video_buffer.hpp"

#include <cassert>
#include <util/lock.hpp>

#include "util/lock.hpp"

namespace irobot::video {

    using namespace irobot::util;

    bool VideoBuffer::init(struct FpsCounter *fps_counter,
                           bool render_expired_frames) {
        VideoBuffer *vb = this;
        this->fps_counter = fps_counter;

        if (!(this->decoding_frame = av_frame_alloc())) {
            goto error_0;
        }

        if (!(this->rendering_frame = av_frame_alloc())) {
            goto error_1;
        }

        if (!(this->mutex = SDL_CreateMutex())) {
            goto error_2;
        }

        this->render_expired_frames = render_expired_frames;
        if (render_expired_frames) {
            if (!(this->rendering_frame_consumed_cond = SDL_CreateCond())) {
                SDL_DestroyMutex(this->mutex);
                goto error_2;
            }
            // interrupted is not used if expired frames are not rendered
            // since offering a frame will never block
            this->interrupted = false;
        }

        // there is initially no rendering frame, so consider it has already been
        // consumed
        this->rendering_frame_consumed = true;

        return true;

        error_2:
        av_frame_free(&this->rendering_frame);
        error_1:
        av_frame_free(&this->decoding_frame);
        error_0:
        return false;
    }

    void VideoBuffer::destroy() {
        if (this->render_expired_frames) {
            SDL_DestroyCond(this->rendering_frame_consumed_cond);
        }
        SDL_DestroyMutex(this->mutex);
        av_frame_free(&this->rendering_frame);
        av_frame_free(&this->decoding_frame);
    }

    void VideoBuffer::swap_frames() {
        AVFrame *tmp = this->decoding_frame;
        this->decoding_frame = this->rendering_frame;
        this->rendering_frame = tmp;
    }

    void VideoBuffer::offer_decoded_frame(
            bool *previous_frame_skipped) {
        mutex_lock(this->mutex);
        if (this->render_expired_frames) {
            // wait for the current (expired) frame to be consumed
            while (!this->rendering_frame_consumed && !this->interrupted) {
                cond_wait(this->rendering_frame_consumed_cond, this->mutex);
            }
        } else if (!this->rendering_frame_consumed) {
            this->fps_counter->add_skipped_frame();
        }

        this->swap_frames();

        *previous_frame_skipped = !this->rendering_frame_consumed;
        this->rendering_frame_consumed = false;

        mutex_unlock(this->mutex);
    }

    const AVFrame *VideoBuffer::consume_rendered_frame() {
        assert(!this->rendering_frame_consumed);
        this->rendering_frame_consumed = true;
        this->fps_counter->add_rendered_frame();
        if (this->render_expired_frames) {
            // unblock video_buffer_offer_decoded_frame()
            cond_signal(this->rendering_frame_consumed_cond);
        }
        return this->rendering_frame;
    }

    void VideoBuffer::interrupt() {
        if (this->render_expired_frames) {
            mutex_lock(this->mutex);
            this->interrupted = true;
            mutex_unlock(this->mutex);
            // wake up blocking wait
            cond_signal(this->rendering_frame_consumed_cond);
        }
    }

}