//
// Created by James Shen on 2/9/26.
// Copyright (c) 2026 GUIDEBEE IT. All rights reserved
//

#include "audio_stream.hpp"

#include "audio_decoder.hpp"
#include "util/buffer_util.hpp"
#include "util/log.hpp"

#define HEADER_SIZE 12
#define PACKET_FLAG_CONFIG    (UINT64_C(1) << 62)
#define PACKET_FLAG_KEY_FRAME (UINT64_C(1) << 61)
#define PACKET_PTS_MASK       (PACKET_FLAG_KEY_FRAME - 1)

// the device always captures/encodes audio at a fixed format
#define AUDIO_SAMPLE_RATE 48000
#define AUDIO_CHANNELS 2

namespace irobot::audio
{
    static enum AVCodecID CodecIdFromRaw(uint32_t raw_codec_id)
    {
        switch (raw_codec_id)
        {
        case 0x6f707573: // "opus"
            return AV_CODEC_ID_OPUS;
        case 0x00616163: // "aac"
            return AV_CODEC_ID_AAC;
        case 0x666c6163: // "flac"
            return AV_CODEC_ID_FLAC;
        case 0x00726177: // "raw"
            return AV_CODEC_ID_PCM_S16LE;
        default:
            return AV_CODEC_ID_NONE;
        }
    }

    bool AudioStream::ReceiveCodecId(uint32_t* codec_id)
    {
        uint8_t buf[4];
        ssize_t r = platform::net_recv_all(this->audio_socket, buf, 4);
        if (r < 4)
        {
            return false;
        }
        *codec_id = util::buffer_read32be(buf);
        return true;
    }

    bool AudioStream::ReceivePacket(AVPacket* packet)
    {
        uint8_t header[HEADER_SIZE];
        ssize_t r = platform::net_recv_all(this->audio_socket, header, HEADER_SIZE);
        if (r < HEADER_SIZE)
        {
            return false;
        }

        uint64_t pts_flags = util::buffer_read64be(header);
        uint32_t len = util::buffer_read32be(&header[8]);
        if (!len)
        {
            LOGE("Invalid zero-length audio packet");
            return false;
        }

        if (av_new_packet(packet, (int)len))
        {
            LOGE("Could not allocate audio packet");
            return false;
        }

        r = platform::net_recv_all(this->audio_socket, packet->data, len);
        if (r < 0 || ((uint32_t)r) < len)
        {
            av_packet_unref(packet);
            return false;
        }

        if (pts_flags & PACKET_FLAG_CONFIG)
        {
            packet->pts = AV_NOPTS_VALUE;
        }
        else
        {
            packet->pts = (int64_t)(pts_flags & PACKET_PTS_MASK);
        }
        if (pts_flags & PACKET_FLAG_KEY_FRAME)
        {
            packet->flags |= AV_PKT_FLAG_KEY;
        }
        packet->dts = packet->pts;
        return true;
    }

    int AudioStream::RunStream(void* data)
    {
        auto* stream = (AudioStream*)data;

        uint32_t raw_codec_id;
        if (!stream->ReceiveCodecId(&raw_codec_id))
        {
            LOGE("Audio stream: connection error while reading codec ID");
            return 0;
        }

        if (raw_codec_id == 0)
        {
            LOGW("Audio disabled by the device (could not capture audio)");
            return 0;
        }
        if (raw_codec_id == 1)
        {
            LOGE("Audio configuration error on the device");
            return 0;
        }

        enum AVCodecID codec_id = CodecIdFromRaw(raw_codec_id);
        if (codec_id == AV_CODEC_ID_NONE)
        {
            LOGE("Unknown audio codec ID: 0x%08x", raw_codec_id);
            return 0;
        }

        const AVCodec* codec = avcodec_find_decoder(codec_id);
        if (!codec)
        {
            LOGE("Audio decoder not found");
            return 0;
        }

        if (!stream->decoder->Open(codec, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS))
        {
            LOGE("Could not open audio decoder");
            return 0;
        }

        for (;;)
        {
            AVPacket packet;
            bool ok = stream->ReceivePacket(&packet);
            if (!ok)
            {
                break;
            }

            ok = stream->decoder->Push(&packet);
            av_packet_unref(&packet);
            if (!ok)
            {
                break;
            }
        }

        LOGD("End of audio frames");

        stream->decoder->Close();

        return 0;
    }

    void AudioStream::Init(socket_t socket, AudioDecoder* pDecoder)
    {
        this->audio_socket = socket;
        this->decoder = pDecoder;
    }

    bool AudioStream::Start()
    {
        LOGD("Starting audio stream thread");
        this->thread = SDL_CreateThread(RunStream, "audio_stream", this);
        if (!this->thread)
        {
            LOGC("Could not start audio stream thread");
            return false;
        }
        return true;
    }

    void AudioStream::Stop()
    {
        // nothing to interrupt explicitly: closing audio_socket (in
        // DeviceServer::Stop) unblocks the blocking recv in RunStream
    }
}
