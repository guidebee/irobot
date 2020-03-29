//
// Created by James Shen on 28/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch.hpp"
#include "util/str_util.hpp"

#if defined (__cplusplus)
extern "C" {
#endif

#include <SDL2/SDL.h>

#if defined (__cplusplus)
}
#endif


TEST_CASE("utility xstrncpy simple", "[util][str_util]") {
    char s[] = "xxxxxxxxxx";
    size_t w = xstrncpy(s, "abcdef", sizeof(s));

    // returns strlen of copied string
    REQUIRE(w == 6);

    // is nul-terminated
    REQUIRE(s[6] == '\0');

    // does not write useless bytes
    REQUIRE(s[7] == 'x');

    // copies the content as expected
    REQUIRE(!strcmp("abcdef", s));
}

TEST_CASE("utility xstrncpy just fit", "[util][str_util]") {
    char s[] = "xxxxxx";
    size_t w = xstrncpy(s, "abcdef", sizeof(s));

    // returns strlen of copied string
    REQUIRE(w == 6);

    // is nul-terminated
    REQUIRE(s[6] == '\0');

    // copies the content as expected
    REQUIRE(!strcmp("abcdef", s));
}

TEST_CASE("utility xstrncpy truncated", "[util][str_util]") {
    char s[] = "xxx";
    size_t w = xstrncpy(s, "abcdef", sizeof(s));

    // returns 'n' (sizeof(s))
    REQUIRE(w == 4);

    // is nul-terminated
    REQUIRE(s[3] == '\0');

    // copies the content as expected
    REQUIRE(!strncmp("abcdef", s, 3));
}

TEST_CASE("utility xstrjoin simple", "[util][str_util]") {
    const char *const tokens[] = {"abc", "de", "fghi", NULL};
    char s[] = "xxxxxxxxxxxxxx";
    size_t w = xstrjoin(s, tokens, ' ', sizeof(s));

    // returns strlen of concatenation
    REQUIRE(w == 11);

    // is nul-terminated
    REQUIRE(s[11] == '\0');

    // does not write useless bytes
    REQUIRE(s[12] == 'x');

    // copies the content as expected
    REQUIRE(!strcmp("abc de fghi", s));
}

TEST_CASE("utility xstrjoin just fit", "[util][str_util]") {
    const char *const tokens[] = {"abc", "de", "fghi", NULL};
    char s[] = "xxxxxxxxxxx";
    size_t w = xstrjoin(s, tokens, ' ', sizeof(s));

    // returns strlen of concatenation
    REQUIRE(w == 11);

    // is nul-terminated
    REQUIRE(s[11] == '\0');

    // copies the content as expected
    REQUIRE(!strcmp("abc de fghi", s));
}

TEST_CASE("utility xstrjoin truncated in token", "[util][str_util]") {
    const char *const tokens[] = {"abc", "de", "fghi", NULL};
    char s[] = "xxxxx";
    size_t w = xstrjoin(s, tokens, ' ', sizeof(s));

    // returns 'n' (sizeof(s))
    REQUIRE(w == 6);

    // is nul-terminated
    REQUIRE(s[5] == '\0');

    // copies the content as expected
    REQUIRE(!strcmp("abc d", s));
}

TEST_CASE("utility xstrjoin truncated before sep", "[util][str_util]") {
    const char *const tokens[] = {"abc", "de", "fghi", NULL};
    char s[] = "xxxxxx";
    size_t w = xstrjoin(s, tokens, ' ', sizeof(s));

    // returns 'n' (sizeof(s))
    REQUIRE(w == 7);

    // is nul-terminated
    REQUIRE(s[6] == '\0');

    // copies the content as expected
    REQUIRE(!strcmp("abc de", s));
}

TEST_CASE("utility xstrjoin truncated after sep", "[util][str_util]") {
    const char *const tokens[] = {"abc", "de", "fghi", NULL};
    char s[] = "xxxxxxx";
    size_t w = xstrjoin(s, tokens, ' ', sizeof(s));

    // returns 'n' (sizeof(s))
    REQUIRE(w == 8);

    // is nul-terminated
    REQUIRE(s[7] == '\0');

    // copies the content as expected
    REQUIRE(!strcmp("abc de ", s));
}

TEST_CASE("utility strquote", "[util][str_util]") {
    const char *s = "abcde";
    char *out = strquote(s);

    // add '"' at the beginning and the end
    REQUIRE(!strcmp("\"abcde\"", out));
    SDL_free(out);
}

TEST_CASE("utility utf8 truncate", "[util][str_util]") {
    const char *s = "aÉbÔc";
    assert(strlen(s) == 7); // É and Ô are 2 bytes-wide

    size_t count;

    count = utf8_truncation_index(s, 1);
    REQUIRE(count == 1);

    count = utf8_truncation_index(s, 2);
    REQUIRE(count == 1); // É is 2 bytes-wide

    count = utf8_truncation_index(s, 3);
    REQUIRE(count == 3);

    count = utf8_truncation_index(s, 4);
    REQUIRE(count == 4);

    count = utf8_truncation_index(s, 5);
    REQUIRE(count == 4); // Ô is 2 bytes-wide

    count = utf8_truncation_index(s, 6);
    REQUIRE(count == 6);

    count = utf8_truncation_index(s, 7);
    REQUIRE(count == 7);

    count = utf8_truncation_index(s, 8);
    REQUIRE(count == 7); // no more chars
}

TEST_CASE("utility parse integer", "[util][str_util]") {
    long value;
    bool ok = parse_integer("1234", &value);
    REQUIRE(ok);
    REQUIRE(value == 1234);

    ok = parse_integer("-1234", &value);
    REQUIRE(ok);
    REQUIRE(value == -1234);

    ok = parse_integer("1234k", &value);
    REQUIRE(!ok);

    ok = parse_integer("123456789876543212345678987654321", &value);
    REQUIRE(!ok); // out-of-range
}

TEST_CASE("utility parse integer with suffix", "[util][str_util]") {
    long value;
    bool ok = parse_integer_with_suffix("1234", &value);
    REQUIRE(ok);
    REQUIRE(value == 1234);

    ok = parse_integer_with_suffix("-1234", &value);
    REQUIRE(ok);
    REQUIRE(value == -1234);

    ok = parse_integer_with_suffix("1234k", &value);
    REQUIRE(ok);
    REQUIRE(value == 1234000);

    ok = parse_integer_with_suffix("1234m", &value);
    REQUIRE(ok);
    REQUIRE(value == 1234000000);

    ok = parse_integer_with_suffix("-1234k", &value);
    REQUIRE(ok);
    REQUIRE(value == -1234000);

    ok = parse_integer_with_suffix("-1234m", &value);
    REQUIRE(ok);
    REQUIRE(value == -1234000000);

    ok = parse_integer_with_suffix("123456789876543212345678987654321", &value);
    REQUIRE(!ok); // out-of-range

    char buf[32];

    sprintf(buf, "%ldk", LONG_MAX / 2000);
    ok = parse_integer_with_suffix(buf, &value);
    REQUIRE(ok);
    REQUIRE(value == LONG_MAX / 2000 * 1000);

    sprintf(buf, "%ldm", LONG_MAX / 2000);
    ok = parse_integer_with_suffix(buf, &value);
    REQUIRE(!ok);

    sprintf(buf, "%ldk", LONG_MIN / 2000);
    ok = parse_integer_with_suffix(buf, &value);
    REQUIRE(ok);
    REQUIRE(value == LONG_MIN / 2000 * 1000);

    sprintf(buf, "%ldm", LONG_MIN / 2000);
    ok = parse_integer_with_suffix(buf, &value);
    REQUIRE(!ok);
}