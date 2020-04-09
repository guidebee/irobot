//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_COMMAND_HPP
#define ANDROID_IROBOT_COMMAND_HPP

#pragma ide diagnostic ignored "OCUnusedMacroInspection"

#if defined (__cplusplus)
extern "C" {
#endif

#ifndef   _POSIX_SOURCE
#define _POSIX_SOURCE // for kill()
#endif
#ifndef _BSD_SOURCE
#define _BSD_SOURCE // for readlink()
#endif
#ifndef _DEFAULT_SOURCE
// modern glibc will complain without this
#define _DEFAULT_SOURCE
#endif

#include <sys/stat.h>
#include <cinttypes>

#ifdef _WIN32

// not needed here, but winsock2.h must never be included AFTER windows.h
# include <winsock2.h>
# include <windows.h>
# define PATH_SEPARATOR '\\'
# define PRIexitcode "lu"
// <https://stackoverflow.com/a/44383330/1987178>
# ifdef _WIN64
#   define PRIsizet PRIu64
# else
#   define PRIsizet PRIu32
# endif
# define PROCESS_NONE NULL
# define NO_EXIT_CODE -1u // max value as unsigned
 typedef HANDLE ProcessType;
 typedef DWORD ExitCodeType;

#else

# include <sys/types.h>

# define PATH_SEPARATOR '/'
# define PRIsizet "zu"
# define PRIexitcode "d"
# define PROCESS_NONE -1
# define NO_EXIT_CODE -1
typedef pid_t ProcessType;
typedef int ExitCodeType;

#endif

#if defined (__cplusplus)
}
#endif

#include <climits>

#include "config.hpp"

namespace irobot::platform {

    enum ProcessResult {
        PROCESS_SUCCESS,
        PROCESS_ERROR_GENERIC,
        PROCESS_ERROR_MISSING_BINARY,
    };

    enum ProcessResult cmd_execute(const char *const argv[], ProcessType *process);

    bool cmd_terminate(ProcessType pid);

    bool cmd_simple_wait(ProcessType pid, ExitCodeType *exit_code);

    ProcessType adb_execute(const char *serial,
                            const char *const adb_cmd[], size_t len);

    ProcessType adb_forward(const char *serial, uint16_t local_port,
                            const char *device_socket_name);

    ProcessType adb_forward_remove(const char *serial,
                                   uint16_t local_port);

    ProcessType adb_reverse(const char *serial,
                            const char *device_socket_name,
                            uint16_t local_port);

    ProcessType adb_reverse_remove(const char *serial,
                                   const char *device_socket_name);

    ProcessType adb_push(const char *serial,
                         const char *local, const char *remote);

    ProcessType adb_install(const char *serial, const char *local);

// convenience function to wait for a successful process execution
// automatically log process errors with the provided process name
    bool process_check_success(ProcessType proc, const char *name);

// return the absolute path of the executable (the irobot binary)
// may be NULL on error; to be freed by SDL_free
    char *get_executable_path();

// returns true if the file exists and is not a directory
    bool is_regular_file(const char *path);

}
#endif //ANDROID_IROBOT_COMMAND_HPP
