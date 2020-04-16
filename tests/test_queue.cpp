//
// Created by James Shen on 27/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch2/catch.hpp"
#include "util/queue.hpp"

struct foo {
    int value;
    struct foo *next;
};

TEST_CASE("utility queue", "[util][queue]") {
    struct my_queue QUEUE(struct foo) queue{};
    queue_init(&queue);

    REQUIRE(queue_is_empty(&queue));

    struct foo v1 = {.value = 42};
    struct foo v2 = {.value = 27};

    queue_push(&queue, next, &v1);
    queue_push(&queue, next, &v2);

    struct foo *foo;

    assert(!queue_is_empty(&queue));
    queue_take(&queue, next, &foo);
    REQUIRE(foo->value == 42);

    REQUIRE(!queue_is_empty(&queue));
    queue_take(&queue, next, &foo);
    REQUIRE(foo->value == 27);

    REQUIRE(queue_is_empty(&queue));
}