//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#if defined (__cplusplus)
extern "C" {
#endif

#include <unistd.h>

#if defined (__cplusplus)
}
#endif


#include "util/net.hpp"


#include "config.hpp"

bool
net_init(void) {
    // do nothing
    return true;
}

void
net_cleanup(void) {
    // do nothing
}

bool
net_close(socket_t socket) {
    return !close(socket);
}
