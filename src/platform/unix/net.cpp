//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "platform/net.hpp"

bool net_init() {
    // do nothing
    return true;
}

void net_cleanup() {
    // do nothing
}

bool net_close(socket_t socket) {
    return !close(socket);
}
