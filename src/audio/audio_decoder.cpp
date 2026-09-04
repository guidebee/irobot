//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#include "audio_decoder.hpp"

#include "audio_buffer.hpp"
#include "util/log.hpp"

#define AUDIO_OUT_SAMPLE_FMT AV_SAMPLE_FMT_S16

namespace irobot::audio
{
    void AudioDecoder::Init(AudioBuffer* buf)
    {
        this->audio_buffer = buf;
        this->codec_ctx = nullptr;
        this->swr_ctx = nullptr;
        this->frame = nullptr;
        this->swr_buf = nullptr;
        this->swr_buf_capacity = 0;
        this->out_sample_rate = 0;
        this->out_channels = 0;
    }

    bool AudioDecoder::Open(const AVCodec* codec, int sample_rate, int channels)
    {
        this->codec_ctx = avcodec_alloc_context3(codec);
        if (!this->codec_ctx)
        {
            LOGC("Could not allocate audio decoder context");
            return false;
        }

        // The device always captures/encodes with a fixed format; the
        // config packet (if any) is not needed to decode individual packets
        this->codec_ctx->sample_rate = sample_rate;
#if LIBAVUTIL_VERSION_MAJOR >= 59
        av_channel_layout_default(&this->codec_ctx->ch_layout, channels);
#else
        this->codec_ctx->channels = channels;
        this->codec_ctx->channel_layout = av_get_default_channel_layout(channels);
#endif

        if (avcodec_open2(this->codec_ctx, codec, nullptr) < 0)
        {
            LOGE("Could not open audio codec");
            avcodec_free_context(&this->codec_ctx);
            return false;
        }

        this->frame = av_frame_alloc();
        if (!this->frame)
        {
            LOGC("Could not allocate audio frame");
            avcodec_free_context(&this->codec_ctx);
            return false;
        }

        this->out_sample_rate = sample_rate;
        this->out_channels = channels;

        return true;
    }

    void AudioDecoder::Close()
    {
        if (this->swr_ctx)
        {
            swr_free(&this->swr_ctx);
        }
        av_freep(&this->swr_buf);
        this->swr_buf_capacity = 0;
        av_frame_free(&this->frame);
        avcodec_free_context(&this->codec_ctx);
    }

    bool AudioDecoder::EnsureResampler()
    {
        if (this->swr_ctx)
        {
            return true;
        }

#if LIBAVUTIL_VERSION_MAJOR >= 59
        AVChannelLayout out_channel_layout;
        av_channel_layout_default(&out_channel_layout, this->out_channels);
        int ret = swr_alloc_set_opts2(&this->swr_ctx,
                                      &out_channel_layout, AUDIO_OUT_SAMPLE_FMT, this->out_sample_rate,
                                      &this->frame->ch_layout, (AVSampleFormat)this->frame->format,
                                      this->frame->sample_rate,
                                      0, nullptr);
        av_channel_layout_uninit(&out_channel_layout);
        if (ret < 0)
        {
            LOGE("Could not configure audio resampler");
            swr_free(&this->swr_ctx);
            return false;
        }
#else
        int64_t in_channel_layout = this->frame->channel_layout
                                        ? (int64_t)this->frame->channel_layout
                                        : av_get_default_channel_layout(this->frame->channels);
        int64_t out_channel_layout = av_get_default_channel_layout(this->out_channels);
        this->swr_ctx = swr_alloc_set_opts(nullptr,
                                           out_channel_layout, AUDIO_OUT_SAMPLE_FMT, this->out_sample_rate,
                                           in_channel_layout, (AVSampleFormat)this->frame->format,
                                           this->frame->sample_rate,
                                           0, nullptr);
#endif
        if (!this->swr_ctx || swr_init(this->swr_ctx) < 0)
        {
            LOGE("Could not initialize audio resampler");
            if (this->swr_ctx)
            {
                swr_free(&this->swr_ctx);
            }
            return false;
        }

        return true;
    }

    bool AudioDecoder::ResampleAndWrite(const AVFrame* decoded)
    {
        if (!this->EnsureResampler())
        {
            return false;
        }

        int64_t delay = swr_get_delay(this->swr_ctx, this->out_sample_rate);
        int out_max_samples = (int)(delay + decoded->nb_samples) + 256;
        int out_bytes_per_sample = av_get_bytes_per_sample(AUDIO_OUT_SAMPLE_FMT);
        int required = out_max_samples * this->out_channels * out_bytes_per_sample;

        if (required > this->swr_buf_capacity)
        {
            av_freep(&this->swr_buf);
            if (av_samples_alloc(&this->swr_buf, nullptr, this->out_channels,
                                 out_max_samples, AUDIO_OUT_SAMPLE_FMT, 0) < 0)
            {
                LOGE("Could not allocate resample buffer");
                this->swr_buf_capacity = 0;
                return false;
            }
            this->swr_buf_capacity = required;
        }

        int converted = swr_convert(this->swr_ctx, &this->swr_buf, out_max_samples,
                                    (const uint8_t**)decoded->data, decoded->nb_samples);
        if (converted < 0)
        {
            LOGE("Audio resampling failed");
            return false;
        }

        size_t bytes = (size_t)converted * this->out_channels * out_bytes_per_sample;
        this->audio_buffer->Write(this->swr_buf, bytes);
        return true;
    }

    bool AudioDecoder::Push(const AVPacket* packet)
    {
        if (packet->pts == AV_NOPTS_VALUE)
        {
            // config packet: not needed to decode individual audio packets
            return true;
        }

        int ret = avcodec_send_packet(this->codec_ctx, packet);
        if (ret < 0 && ret != AVERROR(EAGAIN))
        {
            LOGE("Could not send audio packet: %d", ret);
            return false;
        }

        for (;;)
        {
            ret = avcodec_receive_frame(this->codec_ctx, this->frame);
            if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
            {
                break;
            }
            if (ret < 0)
            {
                LOGE("Could not receive audio frame: %d", ret);
                return false;
            }

            bool ok = this->ResampleAndWrite(this->frame);
            av_frame_unref(this->frame);
            if (!ok)
            {
                return false;
            }
        }

        return true;
    }
}
