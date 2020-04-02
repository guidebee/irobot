//
// Created by James Shen on 28/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch.hpp"
#include "ui/cli.hpp"
#include "common.hpp"

TEST_CASE("flag version", "[ui][cli]") {
    struct scrcpy_cli_args args = {
            .opts = SCRCPY_OPTIONS_DEFAULT,
            .help = false,
            .version = false,
    };

    char *argv[] = {const_cast<char *>("scrcpy"),
                    const_cast<char *>("-v")};

    bool ok = scrcpy_parse_args(&args, 2, argv);
    REQUIRE(ok);
    REQUIRE(!args.help);
    REQUIRE(args.version);
}

TEST_CASE("flag help", "[ui][cli]") {
    struct scrcpy_cli_args args = {
            .opts = SCRCPY_OPTIONS_DEFAULT,
            .help = false,
            .version = false,
    };

    char *argv[] = {const_cast<char *>("scrcpy"),
                    const_cast<char *>("-v")};

    bool ok = scrcpy_parse_args(&args, 2, argv);
    REQUIRE(ok);
    REQUIRE(!args.help);
    REQUIRE(args.version);
}

TEST_CASE("options", "[ui][cli]") {
    struct scrcpy_cli_args args = {
            .opts = SCRCPY_OPTIONS_DEFAULT,
            .help = false,
            .version = false,
    };

    char *argv[] = {
            const_cast<char *>("scrcpy"),
            const_cast<char *>("--always-on-top"),
            const_cast<char *>("--bit-rate"), const_cast<char *>("5M"),
            const_cast<char *>("--crop"), const_cast<char *>("100:200:300:400"),
            const_cast<char *>("--fullscreen"),
            const_cast<char *>("--max-fps"), const_cast<char *>("30"),
            const_cast<char *>("--max-size"), const_cast<char *>("1024"),
            // "--no-control" is not compatible with "--turn-screen-off"
            // "--no-display" is not compatible with "--fulscreen"
            const_cast<char *>("--port"), const_cast<char *>("1234"),
            const_cast<char *>("--push-target"), const_cast<char *>("/sdcard/Movies"),
            const_cast<char *>("--record"), const_cast<char *>("file"),
            const_cast<char *>("--record-format"), const_cast<char *>("mkv"),
            const_cast<char *>("--render-expired-frames"),
            const_cast<char *>("--serial"), const_cast<char *>("0123456789abcdef"),
            const_cast<char *>("--show-touches"),
            const_cast<char *>("--turn-screen-off"),
            const_cast<char *>("--prefer-text"),
            const_cast<char *>("--window-title"), const_cast<char *>("my device"),
            const_cast<char *>("--window-x"), const_cast<char *>("100"),
            const_cast<char *>("--window-y"), const_cast<char *>("-1"),
            const_cast<char *>("--window-width"), const_cast<char *>("600"),
            const_cast<char *>("--window-height"), const_cast<char *>("0"),
            const_cast<char *>("--window-borderless"),
    };

    bool ok = scrcpy_parse_args(&args, ARRAY_LEN(argv), argv);
    REQUIRE(ok);

    const struct IRobotOptions *opts = &args.opts;
    REQUIRE(opts->always_on_top);
//    fprintf(stderr, "%d\n", (int) opts->bit_rate);
    REQUIRE(opts->bit_rate == 5000000);
    REQUIRE(!strcmp(opts->crop, "100:200:300:400"));
    REQUIRE(opts->fullscreen);
    REQUIRE(opts->max_fps == 30);
    REQUIRE(opts->max_size == 1024);
    REQUIRE(opts->port == 1234);
    REQUIRE(!strcmp(opts->push_target, "/sdcard/Movies"));
    REQUIRE(!strcmp(opts->record_filename, "file"));
    REQUIRE(opts->record_format == RECORDER_FORMAT_MKV);
    REQUIRE(opts->render_expired_frames);
    REQUIRE(!strcmp(opts->serial, "0123456789abcdef"));
    REQUIRE(opts->show_touches);
    REQUIRE(opts->turn_screen_off);
    REQUIRE(opts->prefer_text);
    REQUIRE(!strcmp(opts->window_title, "my device"));
    REQUIRE(opts->window_x == 100);
    REQUIRE(opts->window_y == -1);
    REQUIRE(opts->window_width == 600);
    REQUIRE(opts->window_height == 0);
    REQUIRE(opts->window_borderless);
}

TEST_CASE("options2", "[ui][cli]") {
    struct scrcpy_cli_args args = {
            .opts = SCRCPY_OPTIONS_DEFAULT,
            .help = false,
            .version = false,
    };

    char *argv[] = {
            const_cast<char *>("scrcpy"),
            const_cast<char *>("--no-control"),
            const_cast<char *>("--no-display"),
            const_cast<char *>("--record"),
            const_cast<char *>("file.mp4"), // cannot enable --no-display without recording
    };

    bool ok = scrcpy_parse_args(&args, ARRAY_LEN(argv), argv);
    REQUIRE(ok);

    const struct IRobotOptions *opts = &args.opts;
    REQUIRE(!opts->control);
    REQUIRE(!opts->display);
    REQUIRE(!strcmp(opts->record_filename, "file.mp4"));
    REQUIRE(opts->record_format == RECORDER_FORMAT_MP4);
}