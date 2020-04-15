//
// Created by James Shen on 10/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "blob_msg.hpp"
#include "util/buffer_util.hpp"

namespace irobot::message {
    size_t BlobMessage::Serialize(unsigned char *buf) {
        int index = 0;
        util::buffer_write64be(&buf[index], this->type);
        index += 8;
        util::buffer_write64be(&buf[index], this->timestamp);
        index += 8;
        util::buffer_write64be(&buf[index], this->id);
        index += 8;
        util::buffer_write64be(&buf[index], this->count);
        index += 8;
        util::buffer_write64be(&buf[index], this->total_length);
        index += 8;
        for (int i = 0; i < this->count; i++) {
            int length = this->buffers[i].length;
            util::buffer_write64be(&buf[index], length);
            index += 8;
            memcpy(&buf[index], this->buffers[i].data, length + 16);
            index += length + 16;
        }
        return index;
    }


    void BlobMessage::Destroy() {
        for (int i = 0; i < this->count; i++) {
            if (this->buffers[i].data != nullptr) {
                SDL_free(this->buffers[i].data);
                this->buffers[i].data = nullptr;
            }
        }
    }
}