#define CATCH_CONFIG_MAIN

#include "catch.hpp"

#include "util/helper.hpp"

TEST_CASE( "utility helpers", "[util]" ) {
    auto time_of_day= get_current_timestamp();
    REQUIRE( time_of_day > 1 );

}