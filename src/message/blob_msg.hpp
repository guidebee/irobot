//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#pragma ide diagnostic ignored "OCUnusedMacroInspection"
#ifndef ANDROID_IROBOT_BLOB_MSG_HPP
#define ANDROID_IROBOT_BLOB_MSG_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_types.h>

#if defined (__cplusplus)
}
#endif

#define BLOB_MSG_DATA_MAX_COUNT 16
#define BLOB_MSG_SERIALIZED_MAX_SIZE 10485760

#include "util/cbuf.hpp"

namespace irobot::message {

    enum BlobMessageType {
        BLOB_MSG_TYPE_UNKNOWN = 0,
        BLOB_MSG_TYPE_SCREEN_SHOT,
        BLOB_MSG_TYPE_OPENCV_MAT
    };

    struct BlobMessage {
        BlobMessageType type = BLOB_MSG_TYPE_UNKNOWN;
        Uint64 timestamp = 0;
        Uint64 id = 0;
        Uint64 count = 0;
        struct {
            Uint64 length = 0;
            unsigned char *data = nullptr;
        } buffers[BLOB_MSG_DATA_MAX_COUNT];

        // buf size must be at least CONTROL_MSG_SERIALIZED_MAX_SIZE
        // return the number of bytes written
        size_t Serialize(unsigned char *buf);

        void Destroy();

    };

    // only allow 1 buffer, since video image is big,may cause OOM
    struct BlobMessageQueue CBUF(BlobMessage, 1);

}
#endif //ANDROID_IROBOT_BLOB_MSG_HPP

