//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "platform/net.hpp"

#include <csignal>

namespace irobot::platform {
    bool net_init() {
        // do nothing
        signal(SIGPIPE, SIG_IGN);
        return true;
    }

    void net_cleanup() {
        // do nothing
    }

    bool net_close(socket_t socket) {
        return !close(socket);
    }

    bool net_try_recv(socket_t socket) {
        char buf[1];
        recv(socket, (char *) buf, 1, MSG_PEEK | MSG_DONTWAIT);

        return errno > 34 && errno < 45;
    }

}