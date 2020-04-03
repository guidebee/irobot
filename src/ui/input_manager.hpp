//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#ifndef ANDROID_IROBOT_INPUT_MANAGER_HPP
#define ANDROID_IROBOT_INPUT_MANAGER_HPP

#include "config.hpp"
#include "common.hpp"
#include "controller.hpp"

#include "ui/screen.hpp"

#include "video/fps_counter.hpp"
#include "video/video_buffer.hpp"


class InputManager {
public:
    class Controller *controller;

    struct VideoBuffer *video_buffer;
    struct Screen *screen;
    bool prefer_text;

    void process_text_input(
            const SDL_TextInputEvent *event);

    void process_key(
            const SDL_KeyboardEvent *event,
            bool control);

    void process_mouse_motion(
            const SDL_MouseMotionEvent *event);

    void process_touch(
            const SDL_TouchFingerEvent *event);

    void process_mouse_button(
            const SDL_MouseButtonEvent *event,
            bool control);

    void process_mouse_wheel(
            const SDL_MouseWheelEvent *event);

    static void convert_to_renderer_coordinates(SDL_Renderer *renderer, int *x, int *y);

    static struct Point get_mouse_point(Screen *screen);

    static void send_keycode(Controller *controller,
                             enum AndroidKeycode keycode,
                             int actions, const char *name);

    static inline void action_home(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_HOME, actions, "HOME");
    }

    static inline void action_back(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_BACK, actions, "BACK");
    }

    static inline void action_app_switch(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_APP_SWITCH, actions, "APP_SWITCH");
    }

    static inline void action_power(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_POWER, actions, "POWER");
    }

    static inline void action_volume_up(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_VOLUME_UP, actions, "VOLUME_UP");
    }

    static inline void action_volume_down(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_VOLUME_DOWN, actions, "VOLUME_DOWN");
    }

    static inline void action_menu(Controller *controller, int actions) {
        send_keycode(controller, AKEYCODE_MENU, actions, "MENU");
    }

    static void press_back_or_turn_screen_on(Controller *controller);

    static void expand_notification_panel(Controller *controller);

    static void collapse_notification_panel(Controller *controller);

    static void request_device_clipboard(Controller *controller);

    static void set_device_clipboard(Controller *controller);

    static void set_screen_power_mode(Controller *controller,
                                      enum ScreenPowerMode mode);

    static void switch_fps_counter_state(FpsCounter *fps_counter);

    static void clipboard_paste(Controller *controller);

    static void rotate_device(Controller *controller);

    static bool convert_input_key(const SDL_KeyboardEvent *from,
                                  struct ControlMessage *to,
                                  bool prefer_text);

    static bool convert_mouse_motion(const SDL_MouseMotionEvent *from,
                                     Screen *screen,
                                     struct ControlMessage *to);

    static bool convert_touch(const SDL_TouchFingerEvent *from,
                              Screen *screen,
                              struct ControlMessage *to);

    static bool convert_mouse_button(const SDL_MouseButtonEvent *from,
                                     Screen *screen,
                                     struct ControlMessage *to);

    static bool convert_mouse_wheel(const SDL_MouseWheelEvent *from,
                                    Screen *screen,
                                    struct ControlMessage *to);

private:
    bool is_outside_device_screen(int x, int y);
};


#endif //ANDROID_IROBOT_INPUT_MANAGER_HPP
