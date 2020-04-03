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

namespace irobot::video {



    bool VideoStream::recv_packet(AVPacket *packet) {
        // The video stream contains raw packets, without time information. When we
        // record, we retrieve the timestamps separately, from a "meta" header
        // added by the server before each raw packet.
        //
        // The "meta" header length is 12 bytes:
        // [. . . . . . . .|. . . .]. . . . . . . . . . . . . . . ...
        //  <-------------> <-----> <-----------------------------...
        //        PTS        packet        raw packet
        //                    size
        //
        // It is followed by <packet_size> bytes containing the packet/frame.

        uint8_t header[HEADER_SIZE];
        ssize_t r = platform::net_recv_all(this->socket, header, HEADER_SIZE);
        if (r < HEADER_SIZE) {
            return false;
        }

        uint64_t pts = util::buffer_read64be(header);
        uint32_t len = util::buffer_read32be(&header[8]);
        assert(pts == NO_PTS || (pts & 0x8000000000000000) == 0);
        assert(len);

        if (av_new_packet(packet, len)) {
            LOGE("Could not allocate packet");
            return false;
        }

        r = platform::net_recv_all(this->socket, packet->data, len);
        if (r < 0 || ((uint32_t) r) < len) {
            av_packet_unref(packet);
            return false;
        }

        packet->pts = pts != NO_PTS ? (int64_t) pts : AV_NOPTS_VALUE;

        return true;
    }

    void VideoStream::notify_stopped() {
        SDL_Event stop_event;
        stop_event.type = EVENT_STREAM_STOPPED;
        SDL_PushEvent(&stop_event);
    }

    bool VideoStream::process_config_packet(AVPacket *packet) {
        if (this->recorder && !this->recorder->push(packet)) {
            LOGE("Could not send config packet to recorder");
            return false;
        }
        return true;
    }

    bool VideoStream::process_frame(AVPacket *packet) {
        if (this->decoder && !this->decoder->push(packet)) {
            return false;
        }

        if (this->recorder) {
            packet->dts = packet->pts;

            if (!this->recorder->push(packet)) {
                LOGE("Could not send packet to recorder");
                return false;
            }
        }

        return true;
    }

    bool VideoStream::parse(AVPacket *packet) {
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

        bool ok = this->process_frame(packet);
        if (!ok) {
            LOGE("Could not process frame");
            return false;
        }

        return true;
    }

    bool VideoStream::push_packet(AVPacket *packet) {
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
            bool ok = this->process_config_packet(packet);
            if (!ok) {
                return false;
            }
        } else {
            // data packet
            bool ok = this->parse(packet);

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

    int VideoStream::run_stream(void *data) {
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

        if (stream->decoder && !stream->decoder->open(codec)) {
            LOGE("Could not open decoder");
            goto finally_free_codec_ctx;
        }

        if (stream->recorder) {
            if (!stream->recorder->open(codec)) {
                LOGE("Could not open recorder");
                goto finally_close_decoder;
            }

            if (!stream->recorder->start()) {
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
            bool ok = stream->recv_packet(&packet);
            if (!ok) {
                // end of stream
                break;
            }

            ok = stream->push_packet(&packet);
            av_packet_unref(&packet);
            if (!ok) {
                // cannot process packet (error already logged)
                break;
            }
#ifndef UI_SCREEN
            LOGI("Receiving package ...");
#endif
        }

        LOGD("End of frames");

        if (stream->has_pending) {
            av_packet_unref(&stream->pending);
        }

        av_parser_close(stream->parser);
        finally_stop_and_join_recorder:
        if (stream->recorder) {
            stream->recorder->stop();
            LOGI("Finishing recording...");
            stream->recorder->join();
        }
        finally_close_recorder:
        if (stream->recorder) {
            stream->recorder->close();
        }
        finally_close_decoder:
        if (stream->decoder) {
            stream->decoder->close();
        }
        finally_free_codec_ctx:
        avcodec_free_context(&stream->codec_ctx);
        end:
        notify_stopped();
        return 0;
    }

    void VideoStream::init(socket_t socket,
                           struct Decoder *decoder, struct Recorder *recorder) {
        this->socket = socket;
        this->decoder = decoder,
                this->recorder = recorder;
        this->has_pending = false;
    }

    bool VideoStream::start() {
        LOGD("Starting stream thread");
        this->thread = SDL_CreateThread(run_stream, "stream", this);
        if (!this->thread) {
            LOGC("Could not start stream thread");
            return false;
        }
        return true;
    }

    void VideoStream::stop() {
        if (this->decoder) {
            this->decoder->interrupt();
        }
    }

    void VideoStream::join() {

        SDL_WaitThread(this->thread, nullptr);
    }

}