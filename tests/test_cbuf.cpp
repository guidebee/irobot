//
// Created by James Shen on 26/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch.hpp"
#include "util/cbuf.hpp"

struct int_queue CBUF(int, 32);

TEST_CASE( "utility cbuf empty", "[util][cbuf]" ) {
    struct int_queue queue{};
    cbuf_init(&queue);
    REQUIRE(cbuf_is_empty(&queue) );
    bool push_ok = cbuf_push(&queue, 42);
    REQUIRE(push_ok );
    REQUIRE(!cbuf_is_empty(&queue));
    int item;
    bool take_ok = cbuf_take(&queue, &item);
    REQUIRE(take_ok);
    REQUIRE(cbuf_is_empty(&queue));

    bool take_empty_ok = cbuf_take(&queue, &item);
    REQUIRE(!take_empty_ok); // the queue is empty
}

TEST_CASE( "utility cbuf full", "[util][cbuf]" ) {
    struct int_queue queue{};
    cbuf_init(&queue);

    REQUIRE(!cbuf_is_full(&queue));

    // fill the queue
    for (int i = 0; i < 32; ++i) {
        bool ok = cbuf_push(&queue, i);
        REQUIRE(ok);
    }
    bool ok = cbuf_push(&queue, 42);
    REQUIRE(!ok); // the queue if full

    int item;
    bool take_ok = cbuf_take(&queue, &item);
    REQUIRE(take_ok);
    REQUIRE(!cbuf_is_full(&queue));
}

TEST_CASE( "utility cbuf push take", "[util][cbuf]" ) {
    struct int_queue queue{};
    cbuf_init(&queue);

    bool push1_ok = cbuf_push(&queue, 42);
    REQUIRE(push1_ok);

    bool push2_ok = cbuf_push(&queue, 35);
    REQUIRE(push2_ok);

    int item=0;

    bool take1_ok = cbuf_take(&queue, &item);
    REQUIRE(take1_ok);
    REQUIRE(item == 42);

    bool take2_ok = cbuf_take(&queue, &item);
    REQUIRE(take2_ok);
    REQUIRE(item == 35);
}