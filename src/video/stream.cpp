//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "stream.hpp"
#include "recorder.hpp"
#include "ui/events.hpp"
#include "util/buffer_util.hpp"
#include "util/log.hpp"
#include "video/decoder.hpp"

#define HEADER_SIZE 12
#define NO_PTS UINT64_C(-1)

#define PACKET_FLAG_CONFIG    (UINT64_C(1) << 62)
#define PACKET_FLAG_KEY_FRAME (UINT64_C(1) << 61)
#define PACKET_PTS_MASK       (PACKET_FLAG_KEY_FRAME - 1)

namespace irobot::video {

    bool VideoStream::ReceivePacket(AVPacket *packet) {
        // Each 12-byte header is either:
        //   Session packet (MSB of byte 0 = 1): no payload follows, contains new w/h
        //   Media packet  (MSB of byte 0 = 0): PTS+flags (8 bytes) + size (4 bytes),
        //                                       followed by <size> bytes of H.264 data.
        //
        // Media PTS flags (high bits): bit62=CONFIG (SPS/PPS), bit61=KEY_FRAME
        // CONFIG packets have pts = AV_NOPTS_VALUE (triggers PushPacket config path).
        for (;;) {
            uint8_t header[HEADER_SIZE];
            ssize_t r = platform::net_recv_all(this->video_socket, header, HEADER_SIZE);
            if (r < HEADER_SIZE) {
                return false;
            }

            if (header[0] & 0x80) {
                // Session packet: screen was resized/rotated — no payload, just log
                uint32_t w = util::buffer_read32be(&header[4]);
                uint32_t h = util::buffer_read32be(&header[8]);
                LOGI("Session change: %u x %u", w, h);
                continue; // read the next header
            }

            uint64_t pts_flags = util::buffer_read64be(header);
            uint32_t len = util::buffer_read32be(&header[8]);
            if (!len) {
                LOGE("Invalid zero-length packet");
                return false;
            }

            if (av_new_packet(packet, len)) {
                LOGE("Could not allocate packet");
                return false;
            }

            r = platform::net_recv_all(this->video_socket, packet->data, len);
            if (r < 0 || ((uint32_t) r) < len) {
                av_packet_unref(packet);
                return false;
            }

            if (pts_flags & PACKET_FLAG_CONFIG) {
                packet->pts = AV_NOPTS_VALUE;
            } else {
                packet->pts = (int64_t)(pts_flags & PACKET_PTS_MASK);
            }
            if (pts_flags & PACKET_FLAG_KEY_FRAME) {
                packet->flags |= AV_PKT_FLAG_KEY;
            }
            packet->dts = packet->pts;
            return true;
        }
    }

    void VideoStream::NotifyStopped() {
        SDL_Event stop_event;
        stop_event.type = EVENT_STREAM_STOPPED;
        SDL_PushEvent(&stop_event);
    }

    bool VideoStream::ProcessConfigPacket(AVPacket *packet) {
        if (this->recorder && !this->recorder->Push(packet)) {
            LOGE("Could not send config packet to recorder");
            return false;
        }
        return true;
    }

    bool VideoStream::ProcessFrame(AVPacket *packet) {
        if (this->decoder && !this->decoder->Push(packet)) {
            return false;
        }

        if (this->recorder) {
            packet->dts = packet->pts;

            if (!this->recorder->Push(packet)) {
                LOGE("Could not send packet to recorder");
                return false;
            }
        }

        return true;
    }

    bool VideoStream::Parse(AVPacket *packet) {
        uint8_t *in_data = packet->data;
        int in_len = packet->size;
        uint8_t *out_data = nullptr;
        int out_len = 0;
        int r = av_parser_parse2(this->parser, this->codec_ctx,
                                 &out_data, &out_len, in_data, in_len,
                                 AV_NOPTS_VALUE, AV_NOPTS_VALUE, -1);

        // PARSER_FLAG_COMPLETE_FRAMES is set
        assert(r == in_len);
        (void) r;
        assert(out_len == in_len);

        if (this->parser->key_frame == 1) {
            packet->flags |= AV_PKT_FLAG_KEY;
        }

        bool ok = this->ProcessFrame(packet);
        if (!ok) {
            LOGE("Could not process frame");
            return false;
        }

        return true;
    }

    bool VideoStream::PushPacket(AVPacket *packet) {
        bool is_config = packet->pts == AV_NOPTS_VALUE;

        // A config packet must not be decoded immetiately (it contains no
        // frame); instead, it must be concatenated with the future data packet.
        if (this->has_pending || is_config) {
            size_t offset;
            if (this->has_pending) {
                offset = this->pending.size;
                if (av_grow_packet(&this->pending, packet->size)) {
                    LOGE("Could not grow packet");
                    return false;
                }
            } else {
                offset = 0;
                if (av_new_packet(&this->pending, packet->size)) {
                    LOGE("Could not create packet");
                    return false;
                }
                this->has_pending = true;
            }

            memcpy(this->pending.data + offset, packet->data, packet->size);

            if (!is_config) {
                // prepare the concat packet to send to the decoder
                this->pending.pts = packet->pts;
                this->pending.dts = packet->dts;
                this->pending.flags = packet->flags;
                packet = &this->pending;
            }
        }

        if (is_config) {
            // config packet
            bool ok = this->ProcessConfigPacket(packet);
            if (!ok) {
                return false;
            }
        } else {
            // data packet
            bool ok = this->Parse(packet);

            if (this->has_pending) {
                // the pending packet must be discarded (consumed or error)
                this->has_pending = false;
                av_packet_unref(&this->pending);
            }

            if (!ok) {
                return false;
            }
        }
        return true;
    }

    int VideoStream::RunStream(void *data) {
        auto *stream = (struct VideoStream *) data;

        AVCodec *codec = avcodec_find_decoder(AV_CODEC_ID_H264);
        if (!codec) {
            LOGE("H.264 decoder not found");
            goto end;
        }
        stream->codec_ctx = avcodec_alloc_context3(codec);
        if (!stream->codec_ctx) {
            LOGC("Could not allocate codec context");
            goto end;
        }

        if (stream->decoder && !stream->decoder->Open(codec)) {
            LOGE("Could not open decoder");
            goto finally_free_codec_ctx;
        }

        if (stream->recorder) {
            if (!stream->recorder->Open(codec)) {
                LOGE("Could not open recorder");
                goto finally_close_decoder;
            }

            if (!stream->recorder->Start()) {
                LOGE("Could not start recorder");
                goto finally_close_recorder;
            }
        }

        stream->parser = av_parser_init(AV_CODEC_ID_H264);
        if (!stream->parser) {
            LOGE("Could not initialize parser");
            goto finally_stop_and_join_recorder;
        }

        // We must only pass complete frames to av_parser_parse2()!
        // It's more complicated, but this allows to reduce the latency by 1 frame!
        stream->parser->flags |= PARSER_FLAG_COMPLETE_FRAMES;

        for (;;) {
            AVPacket packet;
            bool ok = stream->ReceivePacket(&packet);
            if (!ok) {
                // end of stream
                break;
            }
            ok = stream->PushPacket(&packet);

            av_packet_unref(&packet);
            if (!ok) {
                // cannot process packet (error already logged)
                break;
            }

        }

        LOGD("End of frames");

        if (stream->has_pending) {
            av_packet_unref(&stream->pending);
        }

        av_parser_close(stream->parser);
        finally_stop_and_join_recorder:
        if (stream->recorder) {
            stream->recorder->Stop();
            LOGI("Finishing recording...");
            stream->recorder->Join();
        }
        finally_close_recorder:
        if (stream->recorder) {
            stream->recorder->Close();
        }
        finally_close_decoder:
        if (stream->decoder) {
            stream->decoder->Close();
        }
        finally_free_codec_ctx:
        avcodec_free_context(&stream->codec_ctx);
        end:
        NotifyStopped();
        return 0;
    }

    void VideoStream::Init(socket_t socket,
                           struct Decoder *pDecoder, struct Recorder *pRecorder) {
        this->video_socket = socket;
        this->decoder = pDecoder,
                this->recorder = pRecorder;
        this->has_pending = false;

    }

    bool VideoStream::Start() {
        LOGD("Starting stream thread");
        this->thread = SDL_CreateThread(RunStream, "stream", this);
        if (!this->thread) {
            LOGC("Could not start stream thread");
            return false;
        }
        return true;
    }

    void VideoStream::Stop() {
        if (this->decoder) {
            this->decoder->Interrupt();
        }
    }


}