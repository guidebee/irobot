//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_DEVICE_MSG_HPP
#define ANDROID_IROBOT_DEVICE_MSG_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <unistd.h>

#if defined (__cplusplus)
}
#endif

#include <cstdint>
#include <cstring>

#include "config.hpp"

#define DEVICE_MSG_TEXT_MAX_LENGTH 4093
#define DEVICE_MSG_SERIALIZED_MAX_SIZE (3 + DEVICE_MSG_TEXT_MAX_LENGTH)

namespace irobot::message {

    enum DeviceMessageType {
        DEVICE_MSG_TYPE_CLIPBOARD,
    };

    struct DeviceMessage {
        enum DeviceMessageType type;
        union {
            struct {
                char *text; // owned, to be freed by SDL_free()
            } clipboard;
        };

        ssize_t Deserialize(const unsigned char *buf, size_t len);

        void Destroy();
    };

}
#endif //ANDROID_IROBOT_DEVICE_MSG_HPP
