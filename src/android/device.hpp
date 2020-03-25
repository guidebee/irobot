//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_DEVICE_HPP
#define ANDROID_IROBOT_DEVICE_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <stdbool.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "common.hpp"
#include "util/net.hpp"

#define DEVICE_NAME_FIELD_LENGTH 64

// name must be at least DEVICE_NAME_FIELD_LENGTH bytes
bool
device_read_info(socket_t device_socket, char *device_name, struct size *size);

#endif //ANDROID_IROBOT_DEVICE_HPP
