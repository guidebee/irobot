//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_INPUT_MANAGER_HPP
#define ANDROID_IROBOT_INPUT_MANAGER_HPP

#include "core/common.hpp"
#include "core/controller.hpp"
#include "ui/screen.hpp"
#include "video/fps_counter.hpp"
#include "video/video_buffer.hpp"

namespace irobot::ui {

    using namespace android;
    using namespace message;

    class InputManager {
    public:
        Controller *controller;
        video::VideoBuffer *video_buffer;
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

        static void SendKeycode(Controller *controller,
                                enum AndroidKeycode keycode,
                                int actions, const char *name);

        static inline void ActionHome(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_HOME, actions, "HOME");
        }

        static inline void ActionBack(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_BACK, actions, "BACK");
        }

        static inline void ActionAppSwitch(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_APP_SWITCH, actions, "APP_SWITCH");
        }

        static inline void ActionPower(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_POWER, actions, "POWER");
        }

        static inline void ActionVolumeUp(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_VOLUME_UP, actions, "VOLUME_UP");
        }

        static inline void ActionVolumeDown(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_VOLUME_DOWN, actions, "VOLUME_DOWN");
        }

        static inline void ActionMenu(Controller *controller, int actions) {
            SendKeycode(controller, AKEYCODE_MENU, actions, "MENU");
        }

        static void PressBackOrTurnScreenOn(Controller *controller);

        static void ExpandNotificationPanel(Controller *controller);

        static void CollapseNotificationPanel(Controller *controller);

        static void RequestDeviceClipboard(Controller *controller);

        static void SetDeviceClipboard(Controller *controller);

        static void SetScreenPowerMode(Controller *controller,
                                       enum ScreenPowerMode mode);

        static void SwitchFpsCounterState(video::FpsCounter *fps_counter);

        static void PasteClipboard(Controller *controller);

        static void RotateDevice(Controller *controller);

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
