//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//


#ifndef ANDROID_IROBOT_SERVER_HPP
#define ANDROID_IROBOT_SERVER_HPP

#include <SDL2/SDL_timer.h>
#include <cstdint>

#include "platform/command.hpp"
#include "platform/net.hpp"

namespace irobot {

    struct DeviceServerParameters {
        const char *crop;
        uint16_t local_port;
        uint16_t max_size;
        uint32_t bit_rate;
        uint16_t max_fps;
        bool control;
    };


    class DeviceServer {

    public:
        char *serial;
        ProcessType process;
        socket_t server_socket; // only used if !tunnel_forward
        socket_t video_socket;
        socket_t control_socket;
        uint16_t local_port;
        bool tunnel_enabled;
        bool tunnel_forward; // use "adb forward" instead of "adb reverse"

        // init default values
        void Init();

        // push, enable tunnel et start the server
        bool Start(const char *pSerial,
                   const struct DeviceServerParameters *params);

        // block until the communication with the server is established
        bool ConnectTo();

        // disconnect and kill the server process
        void Stop();

        // close and release sockets
        void Destroy();

        static const char *GetServerPath();

        static bool PushServer(const char *serial);

        static bool EnableTunnelReverse(const char *serial, uint16_t local_port);

        static bool DisableTunnelReverse(const char *serial);

        static bool EnableTunnelForward(const char *serial, uint16_t local_port);

        static bool DisableTunnelForward(const char *serial, uint16_t local_port);

        static socket_t ListenOnPort(uint16_t port);

        static socket_t ConnectAndReadByte(uint16_t port);

        static socket_t ConnectToServer(uint16_t port,
                                        uint32_t attempts, uint32_t delay);

        static void CloseSocket(socket_t *socket);

    private:
        bool EnableTunnel();

        bool DisableTunnel();

        ProcessType ExecuteServer(const struct DeviceServerParameters *params);

    };
}

#endif //ANDROID_IROBOT_SERVER_HPP

