//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_CLI_HPP
#define ANDROID_IROBOT_CLI_HPP

#if defined (__cplusplus)
extern "C" {
#endif
#include <getopt.h>
#include <unistd.h>

#if defined (__cplusplus)
}
#endif

#include "config.hpp"
#include "scrcpy.hpp"

struct scrcpy_cli_args {
    struct scrcpy_options opts;
    bool help;
    bool version;
};

void
scrcpy_print_usage(const char *arg0);

bool
scrcpy_parse_args(struct scrcpy_cli_args *args, int argc, char *argv[]);


#endif //ANDROID_IROBOT_CLI_HPP
