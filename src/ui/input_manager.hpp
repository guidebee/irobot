//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_INPUT_MANAGER_HPP
#define ANDROID_IROBOT_INPUT_MANAGER_HPP

#include "core/common.hpp"
#include "ui/screen.hpp"
#include "ui/events.hpp"
#include "agent/agent_manager.hpp"
#include "video/fps_counter.hpp"
#include "video/video_buffer.hpp"


namespace irobot::ui {

    using namespace android;
    using namespace message;

    class InputManager {
    public:
        agent::AgentManager *null_input_manager;
        Screen *screen;
        bool prefer_text;

        bool EventLoop(bool display, bool control);

        enum EventResult HandleEvent(SDL_Event *event, bool control);

        void ProcessTextInput(const SDL_TextInputEvent *event);

        void ProcessKey(const SDL_KeyboardEvent *event, bool control);

        void ProcessMouseMotion(const SDL_MouseMotionEvent *event);

        void ProcessTouch(const SDL_TouchFingerEvent *event);

        void ProcessMouseButton(const SDL_MouseButtonEvent *event,
                                bool control);

        void ProcessMouseWheel(const SDL_MouseWheelEvent *event);


        static void ConvertToRendererCoordinates(SDL_Renderer *renderer,
                                                 int *x, int *y);

        static struct Point GetMousePoint(Screen *screen);

        void SendKeycode(
                enum AndroidKeycode keycode,
                int actions, const char *name);

        inline void ActionHome(int actions) {
            SendKeycode(AKEYCODE_HOME, actions, "HOME");
        }

        inline void ActionBack(int actions) {
            SendKeycode(AKEYCODE_BACK, actions, "BACK");
        }

        inline void ActionAppSwitch(int actions) {
            SendKeycode(AKEYCODE_APP_SWITCH, actions, "APP_SWITCH");
        }

        inline void ActionPower(int actions) {
            SendKeycode(AKEYCODE_POWER, actions, "POWER");
        }

        inline void ActionVolumeUp(int actions) {
            SendKeycode(AKEYCODE_VOLUME_UP, actions, "VOLUME_UP");
        }

        inline void ActionVolumeDown(int actions) {
            SendKeycode(AKEYCODE_VOLUME_DOWN, actions, "VOLUME_DOWN");
        }

        inline void ActionMenu(int actions) {
            SendKeycode(AKEYCODE_MENU, actions, "MENU");
        }

        void PressBackOrTurnScreenOn();

        void ExpandNotificationPanel();

        void CollapseNotificationPanel();

        void RequestDeviceClipboard();

        void SetDeviceClipboard();

        void SetScreenPowerMode(enum ScreenPowerMode mode);

        static void SwitchFpsCounterState(video::FpsCounter *fps_counter);

        void PasteClipboard();

        void RotateDevice();

        static bool ConvertInputKey(const SDL_KeyboardEvent *from,
                                    ControlMessage *to,
                                    bool prefer_text);

        static bool ConvertMouseMotion(const SDL_MouseMotionEvent *from,
                                       Screen *screen,
                                       ControlMessage *to);

        static bool ConvertTouch(const SDL_TouchFingerEvent *from,
                                 Screen *screen,
                                 ControlMessage *to);

        static bool ConvertMouseButton(const SDL_MouseButtonEvent *from,
                                       Screen *screen,
                                       ControlMessage *to);

        static bool ConvertMouseWheel(const SDL_MouseWheelEvent *from,
                                      Screen *screen,
                                      ControlMessage *to);

        static bool IsApk(const char *file);

        static int EventWatcher(void *data, SDL_Event *event);


    private:
        bool IsOutsideDeviceScreen(int x, int y);
    };

}
#endif //ANDROID_IROBOT_INPUT_MANAGER_HPP
