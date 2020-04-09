//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "device_server.hpp"

#include <cassert>
#include <cinttypes>
#include <cstdio>

#include "config.hpp"
#include "platform/command.hpp"
#include "util/log.hpp"
#include "platform/net.hpp"


#pragma ide diagnostic ignored "OCUnusedGlobalDeclarationInspection"
#define SOCKET_NAME "scrcpy"
#define SERVER_FILENAME "irobot-server"

#define DEFAULT_SERVER_PATH  "./server/" SERVER_FILENAME
#define DEVICE_SERVER_PATH "/data/local/tmp/irobot-server.jar"
#define IPV4_LOCALHOST 0x7F000001

namespace irobot {

    using namespace irobot::platform;

    const char *DeviceServer::GetServerPath() {
        const char *server_path_env = getenv("IROBOT_SERVER_PATH");
        if (server_path_env) {
            LOGD("Using IROBOT_SERVER_PATH: %s", server_path_env);
            // if the envvar is set, use it
            return server_path_env;
        }

#ifndef PORTABLE
        LOGD("Using server: " DEFAULT_SERVER_PATH);
        // the absolute path is hardcoded
        return DEFAULT_SERVER_PATH;
#else
        // use irobot-server in the same directory as the executable
        char *executable_path = get_executable_path();
        if (!executable_path) {
            LOGE("Could not get executable path, "
                 "using " SERVER_FILENAME " from current directory");
            // not found, use current directory
            return SERVER_FILENAME;
        }
        char *dir = dirname(executable_path);
        size_t dirlen = strlen(dir);

        // sizeof(SERVER_FILENAME) gives statically the size including the null byte
        size_t len = dirlen + 1 + sizeof(SERVER_FILENAME);
        char *server_path = SDL_malloc(len);
        if (!server_path) {
            LOGE("Could not alloc server path string, "
                 "using " SERVER_FILENAME " from current directory");
            SDL_free(executable_path);
            return SERVER_FILENAME;
        }

        memcpy(server_path, dir, dirlen);
        server_path[dirlen] = PATH_SEPARATOR;
        memcpy(&server_path[dirlen + 1], SERVER_FILENAME, sizeof(SERVER_FILENAME));
        // the final null byte has been copied with SERVER_FILENAME

        SDL_free(executable_path);

        LOGD("Using server (portable): %s", server_path);
        return server_path;
#endif
    }

    bool DeviceServer::PushServer(const char *serial) {
        const char *server_path = GetServerPath();
        if (!is_regular_file(server_path)) {
            LOGE("'%s' does not exist or is not a regular file\n", server_path);
            return false;
        }
        ProcessType process = adb_push(serial, server_path, DEVICE_SERVER_PATH);
        return process_check_success(process, "adb push");
    }

    bool DeviceServer::EnableTunnelReverse(const char *serial, uint16_t local_port) {
        ProcessType process = adb_reverse(serial, SOCKET_NAME, local_port);
        return process_check_success(process, "adb reverse");
    }

    bool DeviceServer::DisableTunnelReverse(const char *serial) {
        ProcessType process = adb_reverse_remove(serial, SOCKET_NAME);
        return process_check_success(process, "adb reverse --remove");
    }

    bool DeviceServer::EnableTunnelForward(const char *serial, uint16_t local_port) {
        ProcessType process = adb_forward(serial, local_port, SOCKET_NAME);
        return process_check_success(process, "adb forward");
    }

    bool DeviceServer::DisableTunnelForward(const char *serial, uint16_t local_port) {
        ProcessType process = adb_forward_remove(serial, local_port);
        return process_check_success(process, "adb forward --remove");
    }

    bool DeviceServer::EnableTunnel() {
        if (EnableTunnelReverse(this->serial, this->local_port)) {
            return true;
        }

        LOGW("'adb reverse' failed, fallback to 'adb forward'");
        this->tunnel_forward = true;
        return EnableTunnelForward(this->serial, this->local_port);
    }

    bool DeviceServer::DisableTunnel() {
        if (this->tunnel_forward) {
            return DisableTunnelForward(this->serial, this->local_port);
        }
        return DisableTunnelReverse(this->serial);
    }

    ProcessType DeviceServer::ExecuteServer(const struct DeviceServerParameters *params) {
        char max_size_string[6];
        char bit_rate_string[11];
        char max_fps_string[6];
        sprintf(max_size_string, "%" PRIu16, params->max_size);
        sprintf(bit_rate_string, "%" PRIu32, params->bit_rate);
        sprintf(max_fps_string, "%" PRIu16, params->max_fps);
        const char *const cmd[] = {
                "shell",
                "CLASSPATH=" DEVICE_SERVER_PATH, // NOLINT(bugprone-suspicious-missing-comma)
                "app_process",
#ifdef SERVER_DEBUGGER
# define SERVER_DEBUGGER_PORT "5005"
        "-agentlib:jdwp=transport=dt_socket,suspend=y,server=y,address="
            SERVER_DEBUGGER_PORT,
#endif
                "/", // unused
                "com.genymobile.scrcpy.Server",
                IROBOT_SERVER_VERSION,
                max_size_string,
                bit_rate_string,
                max_fps_string,
                this->tunnel_forward ? "true" : "false",
                params->crop ? params->crop : "-",
                "true", // always send frame meta (packet boundaries + timestamp)
                params->control ? "true" : "false",
        };
#ifdef SERVER_DEBUGGER
        LOGI("Server debugger waiting for a client on device port "
             SERVER_DEBUGGER_PORT "...");
        // From the computer, run
        //     adb forward tcp:5005 tcp:5005
        // Then, from Android Studio: Run > Debug > Edit configurations...
        // On the left, click on '+', "Remote", with:
        //     Host: localhost
        //     Port: 5005
        // Then click on "Debug"
#endif
        return adb_execute(this->serial, cmd, sizeof(cmd) / sizeof(cmd[0]));
    }


    socket_t DeviceServer::ListenOnPort(uint16_t port) {
        return net_listen(IPV4_LOCALHOST, port, 1);
    }

    socket_t DeviceServer::ConnectAndReadByte(uint16_t port) {
        socket_t socket = net_connect(IPV4_LOCALHOST, port);
        if (socket == INVALID_SOCKET) {
            return INVALID_SOCKET;
        }

        char byte;
        // the connection may succeed even if the server behind the "adb tunnel"
        // is not listening, so read one byte to detect a working connection
        if (net_recv(socket, &byte, 1) != 1) {
            // the server is not listening yet behind the adb tunnel
            net_close(socket);
            return INVALID_SOCKET;
        }
        return socket;
    }

    socket_t DeviceServer::ConnectToServer(uint16_t port, uint32_t attempts, uint32_t delay) {
        do {
            LOGD("Remaining connection attempts: %d", (int) attempts);
            socket_t socket = ConnectAndReadByte(port);
            if (socket != INVALID_SOCKET) {
                // it worked!
                return socket;
            }
            if (attempts) {
                SDL_Delay(delay);
            }
        } while (--attempts > 0);
        return INVALID_SOCKET;
    }

    void DeviceServer::CloseSocket(socket_t *socket) {
        assert(*socket != INVALID_SOCKET);
        net_shutdown(*socket, SHUT_RDWR);
        if (!net_close(*socket)) {
            LOGW("Could not close socket");
            return;
        }
        *socket = INVALID_SOCKET;
    }

    void DeviceServer::Init() {
        this->serial = nullptr;
        this->process = PROCESS_NONE;
        this->server_socket = INVALID_SOCKET;
        this->video_socket = INVALID_SOCKET;
        this->control_socket = INVALID_SOCKET;
        this->local_port = 0;
        this->tunnel_enabled = false;
        this->tunnel_forward = false;
    }

    bool DeviceServer::Start(const char *serial,
                             const DeviceServerParameters *params) {
        this->local_port = params->local_port;

        if (serial) {
            this->serial = SDL_strdup(serial);
            if (!this->serial) {
                return false;
            }
        }

        if (!PushServer(serial)) {
            SDL_free(this->serial);
            return false;
        }

        if (!EnableTunnel()) {
            SDL_free(this->serial);
            return false;
        }

        // if "adb reverse" does not work (e.g. over "adb connect"), it fallbacks to
        // "adb forward", so the app socket is the client
        if (!this->tunnel_forward) {
            // At the application level, the device part is "the server" because it
            // serves video stream and control. However, at the network level, the
            // client listens and the server connects to the client. That way, the
            // client can listen before starting the server app, so there is no
            // need to try to connect until the server socket is listening on the
            // device.

            this->server_socket = ListenOnPort(params->local_port);
            if (this->server_socket == INVALID_SOCKET) {
                LOGE("Could not listen on port %"
                             PRIu16, params->local_port);
                DisableTunnel();
                SDL_free(this->serial);
                return false;
            }
        }


        // server will connect to our server socket
        this->process = ExecuteServer(params);

        if (this->process == PROCESS_NONE) {
            if (!this->tunnel_forward) {
                CloseSocket(&this->server_socket);
            }
            DisableTunnel();
            SDL_free(this->serial);
            return false;
        }

        this->tunnel_enabled = true;

        return true;
    }


    bool DeviceServer::ConnectTo() {

        if (!this->tunnel_forward) {
            this->video_socket = net_accept(this->server_socket);
            if (this->video_socket == INVALID_SOCKET) {
                return false;
            }

            this->control_socket = net_accept(this->server_socket);
            if (this->control_socket == INVALID_SOCKET) {
                // the video_socket will be cleaned up on destroy
                return false;
            }

            // we don't need the server socket anymore
            CloseSocket(&this->server_socket);
        } else {
            uint32_t attempts = 100;
            uint32_t delay = 100; // ms
            this->video_socket =
                    ConnectToServer(this->local_port, attempts, delay);
            if (this->video_socket == INVALID_SOCKET) {
                return false;
            }

            // we know that the device is listening, we don't need several attempts
            this->control_socket =
                    net_connect(IPV4_LOCALHOST, this->local_port);
            if (this->control_socket == INVALID_SOCKET) {
                return false;
            }
        }

        // we don't need the adb tunnel anymore
        DisableTunnel(); // ignore failure
        this->tunnel_enabled = false;

        return true;
    }

    void DeviceServer::Stop() {

        if (this->server_socket != INVALID_SOCKET) {
            CloseSocket(&this->server_socket);
        }
        if (this->video_socket != INVALID_SOCKET) {
            CloseSocket(&this->video_socket);
        }
        if (this->control_socket != INVALID_SOCKET) {
            CloseSocket(&this->control_socket);
        }

        assert(this->process != PROCESS_NONE);

        if (!cmd_terminate(this->process)) {
            LOGW("Could not terminate server");
        }

        cmd_simple_wait(this->process, nullptr); // ignore exit code
        LOGD("Server terminated");

        if (this->tunnel_enabled) {
            // ignore failure
            DisableTunnel();
        }
    }

    void DeviceServer::Destroy() {
        SDL_free(this->serial);
    }
}
