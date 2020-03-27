//
// Created by James Shen on 26/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch.hpp"
#include "util/buffer_util.hpp"

TEST_CASE( "utility buffer write16be", "[util][buffer]" ) {
    uint16_t val = 0xABCD;
    uint8_t buf[2];
    buffer_write16be(buf, val);
    REQUIRE(buf[0] == 0xAB );
    REQUIRE(buf[1] == 0xCD );
}

TEST_CASE( "utility buffer write32be", "[util][buffer]" ) {
    uint32_t val = 0xABCD1234;
    uint8_t buf[4];
    buffer_write32be(buf, val);
    REQUIRE(buf[0] == 0xAB );
    REQUIRE(buf[1] == 0xCD );
    REQUIRE(buf[2] == 0x12 );
    REQUIRE(buf[3] == 0x34 );
}

TEST_CASE( "utility buffer write64b", "[util][buffer]" ) {
    uint64_t val = 0xABCD1234567890EF;
    uint8_t buf[8];
    buffer_write64be(buf, val);
    REQUIRE(buf[0] == 0xAB );
    REQUIRE(buf[1] == 0xCD );
    REQUIRE(buf[2] == 0x12 );
    REQUIRE(buf[3] == 0x34 );
    REQUIRE(buf[4] == 0x56 );
    REQUIRE(buf[5] == 0x78 );
    REQUIRE(buf[6] == 0x90 );
    REQUIRE(buf[7] == 0xEF );
}

TEST_CASE( "utility buffer read16be", "[util][buffer]" ) {
    uint8_t buf[2] = {0xAB, 0xCD};
    uint16_t val = buffer_read16be(buf);
    REQUIRE(val == 0xABCD );

}

TEST_CASE( "utility buffer read32be", "[util][buffer]" ) {
    uint8_t buf[4] = {0xAB, 0xCD, 0x12, 0x34};
    uint32_t val = buffer_read32be(buf);
    REQUIRE(val == 0xABCD1234 );
}

TEST_CASE( "utility buffer read64be", "[util][buffer]" ) {
    uint8_t buf[8] = {0xAB, 0xCD, 0x12, 0x34,
                      0x56, 0x78, 0x90, 0xEF};
    uint64_t val = buffer_read64be(buf);
    REQUIRE(val == 0xABCD1234567890EF );
}