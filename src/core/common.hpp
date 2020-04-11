//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_COMMON_HPP
#define ANDROID_IROBOT_COMMON_HPP

#include <cstdint>

#define ARRAY_LEN(a) (sizeof(a) / sizeof(a[0]))
#ifndef MIN
#define MIN(X, Y) (X) < (Y) ? (X) : (Y)
#endif
#ifndef MAX
#define MAX(X, Y) (X) > (Y) ? (X) : (Y)
#endif

namespace irobot {

    struct Size {
        uint16_t width;
        uint16_t height;
    };

    struct Point {
        int32_t x;
        int32_t y;
    };

    struct Position {
        // The video screen size may be different from the real device screen size,
        // so store to which size the absolute position apply, to scale it
        // accordingly.
        struct Size screen_size;
        struct Point point;
    };
}
#endif //ANDROID_IROBOT_COMMON_HPP
