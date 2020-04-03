//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "config.hpp"

#include "platform/net.hpp"
#include "util/log.hpp"

bool net_init(void) {
    WSADATA wsa;
    int res = WSAStartup(MAKEWORD(2, 2), &wsa) < 0;
    if (res < 0) {
        LOGC("WSAStartup failed with error %d", res);
        return false;
    }
    return true;
}

void net_cleanup(void) {
    WSACleanup();
}

bool net_close(socket_t socket) {
    return !closesocket(socket);
}
