//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "decoder.hpp"

#include "ui/events.hpp"
#include "util/log.hpp"
#include "video/video_buffer.hpp"

namespace irobot::video {
// set the decoded frame as ready for rendering, and notify
    void Decoder::PushFrame() {
        bool previous_frame_skipped;
        this->video_buffer->OfferDecodedFrame(
                &previous_frame_skipped);
        if (previous_frame_skipped) {
            // the previous EVENT_NEW_FRAME will consume this frame
            return;
        }
        static SDL_Event new_frame_event = {
                .type = EVENT_NEW_FRAME,
        };
        SDL_PushEvent(&new_frame_event);
        static SDL_Event new_opencv_frame_event = {
                .type = EVENT_NEW_OPENCV_FRAME,
        };
        SDL_PushEvent(&new_opencv_frame_event);
    }

    void Decoder::Init(VideoBuffer *vb) {
        this->video_buffer = vb;
        this->sws_cv_ctx = nullptr;

    }

    bool Decoder::Open(const AVCodec *codec) {
        this->codec_ctx = avcodec_alloc_context3(codec);
        if (!this->codec_ctx) {
            LOGC("Could not allocate decoder context");
            return false;
        }
        this->codec_cv_ctx = avcodec_alloc_context3(codec);
        if (!this->codec_cv_ctx) {
            LOGC("Could not allocate decoder context");
            return false;
        }

        if (avcodec_open2(this->codec_ctx, codec, nullptr) < 0) {
            LOGE("Could not open codec");
            avcodec_free_context(&this->codec_ctx);
            return false;
        }

        if (avcodec_open2(this->codec_cv_ctx, codec, nullptr) < 0) {
            LOGE("Could not open codec");
            avcodec_free_context(&this->codec_ctx);
            avcodec_free_context(&this->codec_cv_ctx);
            return false;
        }

        return true;
    }

    void Decoder::Close() {
        avcodec_close(this->codec_ctx);
        avcodec_free_context(&this->codec_ctx);
        avcodec_close(this->codec_cv_ctx);
        avcodec_free_context(&this->codec_cv_ctx);
        sws_freeContext(this->sws_cv_ctx);
        av_free(this->video_buffer->buffer);
        this->sws_cv_ctx = nullptr;
    }

    bool Decoder::Push(const AVPacket *packet) {
        // the new decoding/encoding API has been introduced by:
        // <http://git.videolan.org/?p=ffmpeg.git;a=commitdiff;h=7fc329e2dd6226dfecaa4a1d7adf353bf2773726>
        int ret;
        if ((ret = avcodec_send_packet(this->codec_ctx, packet)) < 0) {
            LOGE("Could not send video packet: %d", ret);
            return false;
        }
        ret = avcodec_receive_frame(this->codec_ctx,
                                    this->video_buffer->decoding_frame);
        if (!ret) {

            if (this->sws_cv_ctx == nullptr) {
                this->codec_cv_ctx->height = this->video_buffer->decoding_frame->height;
                this->codec_cv_ctx->width = video_buffer->decoding_frame->width;
                this->codec_cv_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
                this->codec_cv_ctx->coded_height = this->codec_cv_ctx->height;
                this->codec_cv_ctx->coded_width = this->codec_cv_ctx->width;

                // initialize SWS context for software scaling
                this->sws_cv_ctx = sws_getContext(this->codec_cv_ctx->width,
                                                  this->codec_cv_ctx->height,
                                                  this->codec_cv_ctx->pix_fmt,
                                                  this->codec_cv_ctx->width,
                                                  this->codec_cv_ctx->height,
                                                  AV_PIX_FMT_BGR24,
                                                  SWS_BILINEAR,
                                                  nullptr,
                                                  nullptr,
                                                  nullptr
                );

                if (this->sws_cv_ctx == nullptr) {
                    LOGE("Could not open sws_cv_ctx");
                    avcodec_free_context(&this->codec_ctx);
                    avcodec_free_context(&this->codec_cv_ctx);
                    return false;
                }

                int numBytes = av_image_get_buffer_size(AV_PIX_FMT_RGB24, this->codec_cv_ctx->width,
                                                        this->codec_cv_ctx->height, IMAGE_ALIGN);

                this->video_buffer->rgb_frame->width = this->codec_cv_ctx->width;
                this->video_buffer->rgb_frame->height = this->codec_cv_ctx->height;
                this->video_buffer->rgb_frame->format = AV_PIX_FMT_RGB24;

                this->video_buffer->buffer = (uint8_t *) av_malloc(numBytes * sizeof(uint8_t));

                av_image_fill_arrays(this->video_buffer->rgb_frame->data, this->video_buffer->rgb_frame->linesize,
                                     this->video_buffer->buffer, AV_PIX_FMT_RGB24,
                                     this->codec_cv_ctx->width, this->codec_cv_ctx->height, IMAGE_ALIGN);
            }

            // Convert the image from its native format to RGB
            sws_scale(this->sws_cv_ctx,
                      (uint8_t const *const *) this->video_buffer->decoding_frame->data,
                      this->video_buffer->decoding_frame->linesize,
                      0,
                      this->codec_cv_ctx->height,
                      this->video_buffer->rgb_frame->data,
                      this->video_buffer->rgb_frame->linesize
            );
            this->video_buffer->frame_number = this->codec_ctx->frame_number;
            this->PushFrame();

        } else if (ret != AVERROR(EAGAIN)) {
            LOGE("Could not receive video frame: %d", ret);
            return false;
        }

        return true;
    }

    void Decoder::Interrupt() {
        this->video_buffer->Interrupt();
    }


#pragma ide diagnostic ignored "OCUnusedGlobalDeclarationInspection"

    void Decoder::SaveFrame(AVFrame *pFrameRGB,
                            int iFrame) {
        FILE *pFile;
        char szFilename[32];
        int width = pFrameRGB->width;
        int height = pFrameRGB->height;
        int y;
        // Open file
        sprintf(szFilename, "capture%d.ppm", iFrame);
        pFile = fopen(szFilename, "wb");
        if (pFile == nullptr)
            return;
        // Write header

        fprintf(pFile, "P6\n%d %d\n255\n", width, height);
        // Write pixel data
        for (y = 0; y < height; y++)
            fwrite(pFrameRGB->data[0] + y * pFrameRGB->linesize[0], 1, width * 3, pFile);
        // Close file
        fclose(pFile);
    }


}