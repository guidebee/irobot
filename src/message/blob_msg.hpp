//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_BLOB_MSG_HPP
#define ANDROID_IROBOT_BLOB_MSG_HPP

#include <SDL2/SDL_types.h>
#include "util/cbuf.hpp"

#define BLOB_MSG_DATA_MAX_COUNT 16
#define BLOB_MSG_SERIALIZED_MAX_SIZE 10485760

namespace irobot::message {

    enum BlobMessageType {
        BLOB_MSG_TYPE_UNKNOWN = 0,
        BLOB_MSG_TYPE_SCREEN_SHOT = 1,
        BLOB_MSG_TYPE_OPENCV_MAT = 2
    };

    struct BlobMessage {
        BlobMessageType type = BLOB_MSG_TYPE_UNKNOWN;
        Uint64 timestamp = 0;
        Uint64 id = 0;
        Uint64 count = 0;
        Uint64 total_length = 0;
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
    struct BlobMessageQueue CBUF(BlobMessage, 2);

}
#endif //ANDROID_IROBOT_BLOB_MSG_HPP

