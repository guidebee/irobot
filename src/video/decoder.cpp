//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "decoder.hpp"

#include "ui/events.hpp"
#include "util/log.hpp"
#include "video/video_buffer.hpp"


// set the decoded frame as ready for rendering, and notify
void
Decoder::push_frame() {
    Decoder *decoder = this;
    bool previous_frame_skipped;
    decoder->video_buffer->offer_decoded_frame(
            &previous_frame_skipped);
    if (previous_frame_skipped) {
        // the previous EVENT_NEW_FRAME will consume this frame
        return;
    }
    static SDL_Event new_frame_event = {
            .type = EVENT_NEW_FRAME,
    };
    SDL_PushEvent(&new_frame_event);
}

void
Decoder::init(VideoBuffer *vb) {
    Decoder *decoder = this;
    decoder->video_buffer = vb;
}

bool
Decoder::open(const AVCodec *codec) {
    Decoder *decoder = this;
    decoder->codec_ctx = avcodec_alloc_context3(codec);
    if (!decoder->codec_ctx) {
        LOGC("Could not allocate decoder context");
        return false;
    }

    if (avcodec_open2(decoder->codec_ctx, codec, nullptr) < 0) {
        LOGE("Could not open codec");
        avcodec_free_context(&decoder->codec_ctx);
        return false;
    }

    return true;
}

void
Decoder::close() {
    Decoder *decoder = this;
    avcodec_close(decoder->codec_ctx);
    avcodec_free_context(&decoder->codec_ctx);
}

bool
Decoder::push(const AVPacket *packet) {
// the new decoding/encoding API has been introduced by:
// <http://git.videolan.org/?p=ffmpeg.git;a=commitdiff;h=7fc329e2dd6226dfecaa4a1d7adf353bf2773726>
    Decoder *decoder = this;
    int ret;
    if ((ret = avcodec_send_packet(decoder->codec_ctx, packet)) < 0) {
        LOGE("Could not send video packet: %d", ret);
        return false;
    }
    ret = avcodec_receive_frame(decoder->codec_ctx,
                                decoder->video_buffer->decoding_frame);
    if (!ret) {
        // a frame was received
        decoder->push_frame();
    } else if (ret != AVERROR(EAGAIN)) {
        LOGE("Could not receive video frame: %d", ret);
        return false;
    }

    return true;
}

void
Decoder::interrupt() {
    Decoder *decoder = this;
    decoder->video_buffer->interrupt();
}
