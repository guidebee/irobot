//
// Created by James Shen on 5/4/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch.hpp"
#include <nlohmann/json.hpp>

using nlohmann::json;

TEST_CASE("test json library", "[json]") {
    json::string_t s = R"(["foo",1,2,3,false,{"one":1}])";
    json j = json::parse(s);
    REQUIRE(json::accept(s));
    REQUIRE(j == json({"foo", 1, 2, 3, false, {{"one", 1}}}));

}