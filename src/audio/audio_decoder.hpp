//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_AUDIO_DECODER_HPP
#define ANDROID_IROBOT_AUDIO_DECODER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <libavcodec/avcodec.h>
#include <libavutil/version.h>
#include <libswresample/swresample.h>

#if defined (__cplusplus)
}
#endif

namespace irobot::audio
{
    class AudioBuffer;

    class AudioDecoder
    {
    public:
        AudioBuffer* audio_buffer = nullptr;
        AVCodecContext* codec_ctx = nullptr;
        SwrContext* swr_ctx = nullptr;
        AVFrame* frame = nullptr;
        uint8_t* swr_buf = nullptr;
        int swr_buf_capacity = 0;
        int out_sample_rate = 0;
        int out_channels = 0;

        void Init(AudioBuffer* buf);

        // opens the codec with a fixed output format (the device always
        // captures/encodes at this sample rate and channel count)
        bool Open(const AVCodec* codec, int sample_rate, int channels);

        void Close();

        bool Push(const AVPacket* packet);

    private:
        bool EnsureResampler();

        bool ResampleAndWrite(const AVFrame* decoded);
    };
}

#endif //ANDROID_IROBOT_AUDIO_DECODER_HPP
