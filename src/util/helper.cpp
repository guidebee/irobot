//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "helper.hpp"

#if defined (__cplusplus)
extern "C" {
#endif

#include <cstring>
#include <sys/time.h>

#if defined (__cplusplus)
}
#endif

Uint64 get_current_timestamp() {
    struct timeval tm_now;

    gettimeofday(&tm_now, nullptr);
    Uint64 milli_seconds = tm_now.tv_sec * 1000LL + tm_now.tv_usec / 1000; // calculate milliseconds
    return milli_seconds;

}