//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_DEVICE_HPP
#define ANDROID_IROBOT_DEVICE_HPP

#include "config.hpp"
#include "common.hpp"

#include "platform/net.hpp"

#define DEVICE_NAME_FIELD_LENGTH 64

namespace irobot::android {

    // name must be at least DEVICE_NAME_FIELD_LENGTH bytes
    bool ReadDeviceInfomation(socket_t device_socket,
                              char *device_name, struct Size *size);


}
#endif //ANDROID_IROBOT_DEVICE_HPP
