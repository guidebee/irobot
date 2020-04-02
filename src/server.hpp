//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#pragma ide diagnostic ignored "OCUnusedGlobalDeclarationInspection"
#ifndef ANDROID_IROBOT_SERVER_HPP
#define ANDROID_IROBOT_SERVER_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_timer.h>
#if defined (__cplusplus)
}
#endif

#include <cstdint>

#include "config.hpp"
#include "command.hpp"
#include "util/net.hpp"


struct server_params {
    const char *crop;
    uint16_t local_port;
    uint16_t max_size;
    uint32_t bit_rate;
    uint16_t max_fps;
    bool control;
};


class Server {
public:
    char *serial;
    process_t process;
    socket_t server_socket; // only used if !tunnel_forward
    socket_t video_socket;
    socket_t control_socket;
    socket_t agent_control_server_socket; // agent control server listen socket
    socket_t agent_control_client_socket;// agent control comm socket
    socket_t agent_data_server_socket;  // agent data server listen socket
    uint16_t local_port;
    bool tunnel_enabled;
    bool tunnel_forward; // use "adb forward" instead of "adb reverse"

    // init default values
    void init();

    // push, enable tunnel et start the server
    bool start(const char *serial,
               const struct server_params *params);

    // block until the communication with the server is established
    bool connect_to();

    // disconnect and kill the server process
    void stop();

    // close and release sockets
    void destroy();

};


#endif //ANDROID_IROBOT_SERVER_HPP

