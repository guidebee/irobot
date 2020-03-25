//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "blob_msg.hpp"

#include "util/buffer_util.hpp"


size_t
blob_msg_serialize(const struct blob_msg *msg, unsigned char *buf) {
    int index = 0;
    buffer_write64be(&buf[index], msg->type);
    index += 8;
    buffer_write64be(&buf[index], msg->timestamp);
    index += 8;
    buffer_write64be(&buf[index], msg->id);
    index += 8;
    buffer_write64be(&buf[index], msg->count);
    index += 8;

    for (int i = 0; i < msg->count; i++) {
        int length = msg->buffers[i].length;
        buffer_write64be(&buf[index], length);
        index += 8;
        memcpy(&buf[index], msg->buffers[i].data, length);
        index += length;
    }
    return index;
}

size_t
blob_msg_deserialize(const struct blob_msg *msg, unsigned char *buf, size_t len) {
    return 0;
}

void
blob_msg_destroy(struct blob_msg *msg) {
    Uint64 count = msg->count;
    for (int i = 0; i < count; i++) {
        if (msg->buffers[i].data != NULL) {
            SDL_free(msg->buffers[i].data);
            msg->buffers[i].data = NULL;
        }
    }
}