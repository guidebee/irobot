//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//


#pragma ide diagnostic ignored "OCUnusedGlobalDeclarationInspection"
#ifndef ANDROID_IROBOT_NET_HPP
#define ANDROID_IROBOT_NET_HPP

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL_platform.h>
#include <unistd.h>

#ifdef __WINDOWS__
# include <winsock2.h>

#ifndef SHUT_RDWR
#define SHUT_RDWR SD_BOTH
#endif

typedef SOCKET socket_t;
#else

#include <sys/socket.h>

#define INVALID_SOCKET -1
typedef int socket_t;
#endif

#if defined (__cplusplus)
}
#endif

#include <cstdint>
#include <cerrno>

#define IPV4_LOCALHOST 0x7F000001
//#define IPV4_LOCALHOST 0x00000000

namespace irobot::platform {

    bool net_init();

    void net_cleanup();

    socket_t net_connect(uint32_t addr, uint16_t port);

    socket_t net_listen(uint32_t addr, uint16_t port, int backlog);

    socket_t net_accept(socket_t server_socket);

    bool net_try_recv(socket_t socket);

    // the _all versions wait/retry until len bytes have been written/read
    ssize_t net_recv(socket_t socket, void *buf, size_t len);

    ssize_t net_recv_all(socket_t socket, void *buf, size_t len);

    ssize_t net_send(socket_t socket, const void *buf, size_t len);

    ssize_t net_send_all(socket_t socket, const void *buf, size_t len);

    // how is SHUT_RD (read), SHUT_WR (write) or SHUT_RDWR (both)
    bool net_shutdown(socket_t socket, int how);

    bool net_close(socket_t socket);

    socket_t listen_on_port(uint16_t port);

    void close_socket(socket_t *socket);

}
#endif //ANDROID_IROBOT_NET_HPP

