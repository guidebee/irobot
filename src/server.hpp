//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//


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


struct ServerParameters {
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
    ProcessType process;
    socket_t server_socket; // only used if !tunnel_forward
    socket_t video_socket;
    socket_t control_socket;
    uint16_t local_port;
    bool tunnel_enabled;
    bool tunnel_forward; // use "adb forward" instead of "adb reverse"

    // init default values
    void init();

    // push, enable tunnel et start the server
    bool start(const char *serial,
               const struct ServerParameters *params);

    // block until the communication with the server is established
    bool connect_to();

    // disconnect and kill the server process
    void stop();

    // close and release sockets
    void destroy();

    static const char *get_server_path();

    static bool push_server(const char *serial);

    static bool enable_tunnel_reverse(const char *serial, uint16_t local_port);

    static bool disable_tunnel_reverse(const char *serial);

    static bool enable_tunnel_forward(const char *serial, uint16_t local_port);

    static bool disable_tunnel_forward(const char *serial, uint16_t local_port);

    static socket_t listen_on_port(uint16_t port);

    static socket_t connect_and_read_byte(uint16_t port);

    static socket_t connect_to_server(uint16_t port,
                                      uint32_t attempts, uint32_t delay);

    static void close_socket(socket_t *socket);

private:
    bool enable_tunnel();

    bool disable_tunnel();

    ProcessType execute_server(const struct ServerParameters *params);

};


#endif //ANDROID_IROBOT_SERVER_HPP

