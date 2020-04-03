//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "video_buffer.hpp"

#include <cassert>

#include "util/lock.hpp"

bool
VideoBuffer::init(struct FpsCounter *fps_counter,
                  bool render_expired_frames) {
    VideoBuffer *vb = this;
    vb->fps_counter = fps_counter;

    if (!(vb->decoding_frame = av_frame_alloc())) {
        goto error_0;
    }

    if (!(vb->rendering_frame = av_frame_alloc())) {
        goto error_1;
    }

    if (!(vb->mutex = SDL_CreateMutex())) {
        goto error_2;
    }

    vb->render_expired_frames = render_expired_frames;
    if (render_expired_frames) {
        if (!(vb->rendering_frame_consumed_cond = SDL_CreateCond())) {
            SDL_DestroyMutex(vb->mutex);
            goto error_2;
        }
        // interrupted is not used if expired frames are not rendered
        // since offering a frame will never block
        vb->interrupted = false;
    }

    // there is initially no rendering frame, so consider it has already been
    // consumed
    vb->rendering_frame_consumed = true;

    return true;

    error_2:
    av_frame_free(&vb->rendering_frame);
    error_1:
    av_frame_free(&vb->decoding_frame);
    error_0:
    return false;
}

void
VideoBuffer::destroy() {
    VideoBuffer *vb = this;
    if (vb->render_expired_frames) {
        SDL_DestroyCond(vb->rendering_frame_consumed_cond);
    }
    SDL_DestroyMutex(vb->mutex);
    av_frame_free(&vb->rendering_frame);
    av_frame_free(&vb->decoding_frame);
}

void
VideoBuffer::swap_frames() {
    VideoBuffer *vb = this;
    AVFrame *tmp = vb->decoding_frame;
    vb->decoding_frame = vb->rendering_frame;
    vb->rendering_frame = tmp;
}

void
VideoBuffer::offer_decoded_frame(
        bool *previous_frame_skipped) {
    VideoBuffer *vb = this;
    mutex_lock(vb->mutex);
    if (vb->render_expired_frames) {
        // wait for the current (expired) frame to be consumed
        while (!vb->rendering_frame_consumed && !vb->interrupted) {
            cond_wait(vb->rendering_frame_consumed_cond, vb->mutex);
        }
    } else if (!vb->rendering_frame_consumed) {
        vb->fps_counter->add_skipped_frame();
    }

    vb->swap_frames();

    *previous_frame_skipped = !vb->rendering_frame_consumed;
    vb->rendering_frame_consumed = false;

    mutex_unlock(vb->mutex);
}

const AVFrame *
VideoBuffer::consume_rendered_frame() {
    VideoBuffer *vb = this;
    assert(!vb->rendering_frame_consumed);
    vb->rendering_frame_consumed = true;
    vb->fps_counter->add_rendered_frame();
    if (vb->render_expired_frames) {
        // unblock video_buffer_offer_decoded_frame()
        cond_signal(vb->rendering_frame_consumed_cond);
    }
    return vb->rendering_frame;
}

void
VideoBuffer::interrupt() {
    VideoBuffer *vb = this;
    if (vb->render_expired_frames) {
        mutex_lock(vb->mutex);
        vb->interrupted = true;
        mutex_unlock(vb->mutex);
        // wake up blocking wait
        cond_signal(vb->rendering_frame_consumed_cond);
    }
}
