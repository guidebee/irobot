//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_COMMON_HPP
#define ANDROID_IROBOT_COMMON_HPP
#if defined (__cplusplus)
extern "C" {
#endif

#include <stdint.h>

#if defined (__cplusplus)
}
#endif
#include "config.hpp"

#define ARRAY_LEN(a) (sizeof(a) / sizeof(a[0]))
#define MIN(X, Y) (X) < (Y) ? (X) : (Y)
#define MAX(X, Y) (X) > (Y) ? (X) : (Y)

struct size {
    uint16_t width;
    uint16_t height;
};

struct point {
    int32_t x;
    int32_t y;
};

struct position {
    // The video screen size may be different from the real device screen size,
    // so store to which size the absolute position apply, to scale it
    // accordingly.
    struct size screen_size;
    struct point point;
};

#endif //ANDROID_IROBOT_COMMON_HPP
