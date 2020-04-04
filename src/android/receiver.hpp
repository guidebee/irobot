//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_RECEIVER_HPP
#define ANDROID_IROBOT_RECEIVER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_mutex.h>
#include <SDL2/SDL_thread.h>

#if defined (__cplusplus)
}
#endif

#include "core/common.hpp"
#include "message/device_msg.hpp"
#include "platform/net.hpp"

#define DEVICE_NAME_FIELD_LENGTH 64

namespace irobot::android {

// receive events from the device
// managed by the controller
    class Receiver {

    public:
        socket_t control_socket;
        SDL_Thread *thread;
        SDL_mutex *mutex;

        bool Init(socket_t control_socket);

        void Destroy();

        bool Start();

        // no receiver_stop(), it will automatically stop on control_socket shutdown

        void Join();

        static void ProcessMessage(struct message::DeviceMessage *msg);

        static ssize_t ProcessMessages(const unsigned char *buf, size_t len);

        static int RunReceiver(void *data);

        // name must be at least DEVICE_NAME_FIELD_LENGTH bytes
        static bool ReadDeviceInfomation(socket_t device_socket,
                                         char *device_name, struct Size *size);
    };
}
#endif //ANDROID_IROBOT_RECEIVER_HPP
