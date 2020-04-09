//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "video_buffer.hpp"

#include <cassert>
#include <util/lock.hpp>

namespace irobot::video {

    bool VideoBuffer::Init(struct FpsCounter *fps_counter,
                           bool render_expired_frames) {
        this->fps_counter = fps_counter;

        if (!(this->decoding_frame = av_frame_alloc())) {
            goto error_0;
        }

        if (!(this->rendering_frame = av_frame_alloc())) {
            goto error_1;
        }

        if (!(this->rgb_frame = av_frame_alloc())) {
            goto error_2;
        }

        if (!(this->mutex = SDL_CreateMutex())) {
            goto error_3;
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

        error_3:
        av_frame_free(&this->rgb_frame);
        error_2:
        av_frame_free(&this->rendering_frame);
        error_1:
        av_frame_free(&this->decoding_frame);
        error_0:
        return false;
    }

    void VideoBuffer::Destroy() {
        if (this->render_expired_frames) {
            SDL_DestroyCond(this->rendering_frame_consumed_cond);
        }
        SDL_DestroyMutex(this->mutex);
        av_frame_free(&this->rendering_frame);
        av_frame_free(&this->decoding_frame);
        av_frame_free(&this->rgb_frame);
        this->fps_counter->Destroy();
    }

    void VideoBuffer::SwapFrames() {
        AVFrame *tmp = this->decoding_frame;
        this->decoding_frame = this->rendering_frame;
        this->rendering_frame = tmp;
    }

    void VideoBuffer::OfferDecodedFrame(
            bool *previous_frame_skipped) {
        util::mutex_lock(this->mutex);
        if (this->render_expired_frames) {
            // wait for the current (expired) frame to be consumed
            while (!this->rendering_frame_consumed && !this->interrupted) {
                util::cond_wait(this->rendering_frame_consumed_cond, this->mutex);
            }
        } else if (!this->rendering_frame_consumed) {
            this->fps_counter->AddSkippedFrame();
        }

        this->SwapFrames();

        *previous_frame_skipped = !this->rendering_frame_consumed;
        this->rendering_frame_consumed = false;

        util::mutex_unlock(this->mutex);
    }

    const AVFrame *VideoBuffer::ConsumeRenderedFrame() {
        assert(!this->rendering_frame_consumed);
        this->rendering_frame_consumed = true;
        this->fps_counter->AddRenderedFrame();
        if (this->render_expired_frames) {
            // unblock video_buffer_offer_decoded_frame()
            util::cond_signal(this->rendering_frame_consumed_cond);
        }
        return this->rendering_frame;
    }

    void VideoBuffer::Interrupt() {
        if (this->render_expired_frames) {
            util::mutex_lock(this->mutex);
            this->interrupted = true;
            util::mutex_unlock(this->mutex);
            // wake up blocking wait
            util::cond_signal(this->rendering_frame_consumed_cond);
        }
    }

}