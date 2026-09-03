//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "config.hpp"

#include "platform/net.hpp"
#include "util/log.hpp"

#include <windows.h>
#include <SDL2/SDL_events.h>

namespace irobot::platform
{
    namespace
    {
        // Ctrl+C in the console (or a close/logoff/shutdown request) does not
        // reliably reach irobot's main thread otherwise: the default action
        // just calls ExitProcess(), which skips the app's own cleanup (closing
        // sockets, restoring show_touches, stopping the adb tunnel). Route it
        // through the same graceful-quit path as clicking the window's close
        // button.
        BOOL WINAPI ConsoleCtrlHandler(DWORD ctrl_type)
        {
            switch (ctrl_type)
            {
            case CTRL_C_EVENT:
            case CTRL_BREAK_EVENT:
            case CTRL_CLOSE_EVENT:
            case CTRL_LOGOFF_EVENT:
            case CTRL_SHUTDOWN_EVENT:
                {
                    SDL_Event quit_event;
                    quit_event.type = SDL_QUIT;
                    SDL_PushEvent(&quit_event);
                    return TRUE;
                }
            default:
                return FALSE;
            }
        }
    }

    bool net_init(void)
    {
        WSADATA wsa;
        int res = WSAStartup(MAKEWORD(2, 2), &wsa) < 0;
        if (res < 0)
        {
            LOGC("WSAStartup failed with error %d", res);
            return false;
        }

        if (!SetConsoleCtrlHandler(ConsoleCtrlHandler, TRUE))
        {
            LOGW("Could not register console control handler");
        }

        return true;
    }

    void net_cleanup(void)
    {
        WSACleanup();
    }

    bool net_close(socket_t socket)
    {
        return !closesocket(socket);
    }

}