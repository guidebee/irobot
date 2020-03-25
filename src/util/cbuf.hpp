//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CBUF_HPP
#define ANDROID_IROBOT_CBUF_HPP

#if defined (__cplusplus)
extern "C" {
#endif
#include <cstdbool>
#include <unistd.h>

#if defined (__cplusplus)
}
#endif


// To define a circular buffer type of 20 ints:
//     struct cbuf_int CBUF(int, 20);
//
// data has length CAP + 1 to distinguish empty vs full.
#define CBUF(TYPE, CAP) { \
    TYPE data[(CAP) + 1]; \
    size_t head; \
    size_t tail; \
}

#define cbuf_size_(PCBUF) \
    (sizeof((PCBUF)->data) / sizeof(*(PCBUF)->data))

#define cbuf_is_empty(PCBUF) \
    ((PCBUF)->head == (PCBUF)->tail)

#define cbuf_is_full(PCBUF) \
    (((PCBUF)->head + 1) % cbuf_size_(PCBUF) == (PCBUF)->tail)

#define cbuf_init(PCBUF) \
    (void) ((PCBUF)->head = (PCBUF)->tail = 0)

#define cbuf_push(PCBUF, ITEM) \
    ({ \
        bool ok = !cbuf_is_full(PCBUF); \
        if (ok) { \
            (PCBUF)->data[(PCBUF)->head] = (ITEM); \
            (PCBUF)->head = ((PCBUF)->head + 1) % cbuf_size_(PCBUF); \
        } \
        ok; \
    })

#define cbuf_take(PCBUF, PITEM) \
    ({ \
        bool ok = !cbuf_is_empty(PCBUF); \
        if (ok) { \
            *(PITEM) = (PCBUF)->data[(PCBUF)->tail]; \
            (PCBUF)->tail = ((PCBUF)->tail + 1) % cbuf_size_(PCBUF); \
        } \
        ok; \
    })

#endif //ANDROID_IROBOT_CBUF_HPP