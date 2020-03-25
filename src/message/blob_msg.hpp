//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

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

#define BLOB_MSG_TYPE_RECORDED_EVENTS       0x1
#define BLOB_MSG_TYPE_SCREEN_SHOT           0x2
#define BLOB_MSG_TYPE_OPENCV_MAT            0x3

struct blob_msg {
    Uint64 type;
    Uint64 timestamp;
    Uint64 id;
    Uint64 count;
    struct {
        Uint64 length;
        unsigned char *data;
    } buffers[BLOB_MSG_DATA_MAX_COUNT];

};

size_t
blob_msg_serialize(const struct blob_msg *msg, unsigned char *buf);

size_t
blob_msg_deserialize(const struct blob_msg *msg, unsigned char *buf, size_t len);

void
blob_msg_destroy(struct blob_msg *msg);

#endif //ANDROID_IROBOT_BLOB_MSG_HPP
