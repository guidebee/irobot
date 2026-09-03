//
// Created by James Shen on 24/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "platform/net.hpp"

#include <csignal>
#include <SDL2/SDL_events.h>

namespace irobot::platform
{
    namespace
    {
        // route SIGINT/SIGTERM through the same graceful-quit path as
        // clicking the window's close button, instead of the default abrupt
        // termination which skips the app's own cleanup.
        void QuitSignalHandler(int)
        {
            SDL_Event quit_event;
            quit_event.type = SDL_QUIT;
            SDL_PushEvent(&quit_event);
        }
    }

    bool net_init()
    {
        // do nothing
        signal(SIGPIPE, SIG_IGN);
        signal(SIGINT, QuitSignalHandler);
        signal(SIGTERM, QuitSignalHandler);
        return true;
    }

    void net_cleanup()
    {
        // do nothing
    }

    bool net_close(socket_t socket)
    {
        return !close(socket);
    }

}