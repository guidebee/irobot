//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//
#pragma ide diagnostic ignored "hicpp-signed-bitwise"

#include "input_manager.hpp"

#include <cassert>

#include "ui/event_converter.hpp"
#include "util/lock.hpp"
#include "util/log.hpp"
#include "message/control_msg.hpp"

namespace irobot::ui {

    static const int ACTION_DOWN = 1;
    static const int ACTION_UP = 1 << 1;

// Convert window coordinates (as provided by SDL_GetMouseState() to renderer
// coordinates (as provided in SDL mouse events)
//
// See my question:
// <https://stackoverflow.com/questions/49111054/how-to-get-mouse-position-on-mouse-wheel-event>
    void InputManager::convert_to_renderer_coordinates(SDL_Renderer *renderer,
                                                       int *x, int *y) {
        SDL_Rect viewport;
        float scale_x, scale_y;
        SDL_RenderGetViewport(renderer, &viewport);
        SDL_RenderGetScale(renderer, &scale_x, &scale_y);
        *x = (int) (static_cast<float>(*x) / scale_x) - viewport.x;
        *y = (int) (static_cast<float>(*y) / scale_y) - viewport.y;
    }

    struct Point InputManager::get_mouse_point(Screen *screen) {
        int x;
        int y;
        SDL_GetMouseState(&x, &y);
        convert_to_renderer_coordinates(screen->renderer, &x, &y);
        return (struct Point) {
                .x = x,
                .y = y,
        };
    }


    void InputManager::send_keycode(Controller *controller, enum AndroidKeycode keycode,
                                    int actions, const char *name) {
        // send DOWN event
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_INJECT_KEYCODE;
        msg.inject_keycode.keycode = keycode;
        msg.inject_keycode.metastate = static_cast<AndroidMetaState>(0);

        if (actions & ACTION_DOWN) {
            msg.inject_keycode.action = AKEY_EVENT_ACTION_DOWN;
            if (!controller->push_msg(&msg)) {
                LOGW("Could not request 'inject %s (DOWN)'", name);
                return;
            }
        }

        if (actions & ACTION_UP) {
            msg.inject_keycode.action = AKEY_EVENT_ACTION_UP;
            if (!controller->push_msg(&msg)) {
                LOGW("Could not request 'inject %s (UP)'", name);
            }
        }
    }


// turn the screen on if it was off, press BACK otherwise
    void InputManager::press_back_or_turn_screen_on(Controller *controller) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON;

        if (!controller->push_msg(&msg)) {
            LOGW("Could not request 'press back or turn screen on'");
        }
    }

    void InputManager::expand_notification_panel(Controller *controller) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL;

        if (!controller->push_msg(&msg)) {
            LOGW("Could not request 'expand notification panel'");
        }
    }

    void InputManager::collapse_notification_panel(Controller *controller) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL;

        if (!controller->push_msg(&msg)) {
            LOGW("Could not request 'collapse notification panel'");
        }
    }

    void InputManager::request_device_clipboard(Controller *controller) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_GET_CLIPBOARD;

        if (!controller->push_msg(&msg)) {
            LOGW("Could not request device clipboard");
        }
    }

    void InputManager::set_device_clipboard(Controller *controller) {
        char *text = SDL_GetClipboardText();
        if (!text) {
            LOGW("Could not get clipboard text: %s", SDL_GetError());
            return;
        }
        if (!*text) {
            // empty text
            SDL_free(text);
            return;
        }

        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_SET_CLIPBOARD;
        msg.set_clipboard.text = text;

        if (!controller->push_msg(&msg)) {
            SDL_free(text);
            LOGW("Could not request 'set device clipboard'");
        }
    }

    void InputManager::set_screen_power_mode(Controller *controller,
                                             enum ScreenPowerMode mode) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE;
        msg.set_screen_power_mode.mode = mode;

        if (!controller->push_msg(&msg)) {
            LOGW("Could not request 'set screen power mode'");
        }
    }

    void InputManager::switch_fps_counter_state(video::FpsCounter *fps_counter) {
        // the started state can only be written from the current thread, so there
        // is no ToCToU issue
        if (fps_counter->is_started()) {
            fps_counter->stop();
            LOGI("FPS counter stopped");
        } else {
            if (fps_counter->start()) {
                LOGI("FPS counter started");
            } else {
                LOGE("FPS counter starting failed");
            }
        }
    }

    void InputManager::clipboard_paste(Controller *controller) {
        char *text = SDL_GetClipboardText();
        if (!text) {
            LOGW("Could not get clipboard text: %s", SDL_GetError());
            return;
        }
        if (!*text) {
            // empty text
            SDL_free(text);
            return;
        }

        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_INJECT_TEXT;
        msg.inject_text.text = text;
        if (!controller->push_msg(&msg)) {
            SDL_free(text);
            LOGW("Could not request 'paste clipboard'");
        }
    }

    void InputManager::rotate_device(Controller *controller) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_ROTATE_DEVICE;

        if (!controller->push_msg(&msg)) {
            LOGW("Could not request device rotation");
        }
    }

    void InputManager::process_text_input(
            const SDL_TextInputEvent *event) {
        if (!this->prefer_text) {
            char c = event->text[0];
            if (isalpha(c) || c == ' ') {
                assert(event->text[1] == '\0');
                // letters and space are handled as raw key event
                return;
            }
        }

        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_INJECT_TEXT;
        msg.inject_text.text = SDL_strdup(event->text);
        if (!msg.inject_text.text) {
            LOGW("Could not strdup input text");
            return;
        }
        if (!this->controller->push_msg(&msg)) {
            SDL_free(msg.inject_text.text);
            LOGW("Could not request 'inject text'");
        }
    }

    bool InputManager::convert_input_key(const SDL_KeyboardEvent *from,
                                         struct ControlMessage *to,
                                         bool prefer_text) {
        to->type = CONTROL_MSG_TYPE_INJECT_KEYCODE;

        if (!convert_keycode_action(static_cast<SDL_EventType>(from->type), &to->inject_keycode.action)) {
            return false;
        }

        uint16_t mod = from->keysym.mod;
        if (!convert_keycode(from->keysym.sym, &to->inject_keycode.keycode, mod,
                             prefer_text)) {
            return false;
        }

        to->inject_keycode.metastate = convert_meta_state(static_cast<SDL_Keymod>(mod));

        return true;
    }

    void InputManager::process_key(
            const SDL_KeyboardEvent *event,
            bool control) {
        // control: indicates the state of the command-line option --no-control
        // ctrl: the Ctrl key

        bool ctrl = event->keysym.mod & (KMOD_LCTRL | KMOD_RCTRL);
        bool alt = event->keysym.mod & (KMOD_LALT | KMOD_RALT);
        bool meta = event->keysym.mod & (KMOD_LGUI | KMOD_RGUI);

        // use Cmd on macOS, Ctrl on other platforms
#ifdef __APPLE__
        bool cmd = !ctrl && meta;
#else
        if (meta) {
            // no shortcuts involve Meta on platforms other than macOS, and it must
            // not be forwarded to the device
            return;
        }
        bool cmd = ctrl; // && !meta, already guaranteed
#endif

        if (alt) {
            // no shortcuts involve Alt, and it must not be forwarded to the device
            return;
        }

        Controller *controller = this->controller;

        // capture all Ctrl events
        if (ctrl || cmd) {
            SDL_Keycode keycode = event->keysym.sym;
            bool down = event->type == SDL_KEYDOWN;
            int action = down ? ACTION_DOWN : ACTION_UP;
            bool repeat = event->repeat;
            bool shift = event->keysym.mod & (KMOD_LSHIFT | KMOD_RSHIFT);
            switch (keycode) {
                case SDLK_h:
                    // Ctrl+h on all platform, since Cmd+h is already captured by
                    // the system on macOS to hide the window
                    if (control && ctrl && !meta && !shift && !repeat) {
                        action_home(controller, action);
                    }
                    return;
                case SDLK_b: // fall-through
                case SDLK_BACKSPACE:
                    if (control && cmd && !shift && !repeat) {
                        action_back(controller, action);
                    }
                    return;
                case SDLK_s:
                    if (control && cmd && !shift && !repeat) {
                        action_app_switch(controller, action);
                    }
                    return;
                case SDLK_m:
                    // Ctrl+m on all platform, since Cmd+m is already captured by
                    // the system on macOS to minimize the window
                    if (control && ctrl && !meta && !shift && !repeat) {
                        action_menu(controller, action);
                    }
                    return;
                case SDLK_p:
                    if (control && cmd && !shift && !repeat) {
                        action_power(controller, action);
                    }
                    return;
                case SDLK_o:
                    if (control && cmd && !shift && down) {
                        set_screen_power_mode(controller, SCREEN_POWER_MODE_OFF);
                    }
                    return;
                case SDLK_DOWN:
                    if (control && cmd && !shift) {
                        // forward repeated events
                        action_volume_down(controller, action);
                    }
                    return;
                case SDLK_UP:
                    if (control && cmd && !shift) {
                        // forward repeated events
                        action_volume_up(controller, action);
                    }
                    return;
                case SDLK_c:
                    if (control && cmd && !shift && !repeat && down) {
                        request_device_clipboard(controller);
                    }
                    return;
                case SDLK_v:
                    if (control && cmd && !repeat && down) {
                        if (shift) {
                            // store the text in the device clipboard
                            set_device_clipboard(controller);
                        } else {
                            // inject the text as input events
                            clipboard_paste(controller);
                        }
                    }
                    return;
                case SDLK_f:
                    if (!shift && cmd && !repeat && down) {
                        this->screen->switch_fullscreen();
                    }
                    return;
                case SDLK_x:
                    if (!shift && cmd && !repeat && down) {
                        this->screen->resize_to_fit();
                    }
                    return;
                case SDLK_g:
                    if (!shift && cmd && !repeat && down) {
                        this->screen->resize_to_pixel_perfect();
                    }
                    return;
                case SDLK_i:
                    if (!shift && cmd && !repeat && down) {
                        struct video::FpsCounter *fps_counter =
                                this->video_buffer->fps_counter;
                        switch_fps_counter_state(fps_counter);
                    }
                    return;
                case SDLK_n:
                    if (control && cmd && !repeat && down) {
                        if (shift) {
                            collapse_notification_panel(controller);
                        } else {
                            expand_notification_panel(controller);
                        }
                    }
                    return;
                case SDLK_r:
                    if (control && cmd && !shift && !repeat && down) {
                        rotate_device(controller);
                    }
                    return;
                default:
                    break;
            }

            return;
        }

        if (!control) {
            return;
        }

        struct ControlMessage msg{};
        if (convert_input_key(event, &msg, this->prefer_text)) {
            if (!controller->push_msg(&msg)) {
                LOGW("Could not request 'inject keycode'");
            }
        }
    }

    bool InputManager::convert_mouse_motion(const SDL_MouseMotionEvent *from,
                                            Screen *screen,
                                            struct ControlMessage *to) {
        to->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;
        to->inject_touch_event.action = AMOTION_EVENT_ACTION_MOVE;
        to->inject_touch_event.pointer_id = POINTER_ID_MOUSE;
        to->inject_touch_event.position.screen_size = screen->frame_size;
        to->inject_touch_event.position.point.x = from->x;
        to->inject_touch_event.position.point.y = from->y;
        to->inject_touch_event.pressure = 1.f;
        to->inject_touch_event.buttons = convert_mouse_buttons(from->state);

        return true;
    }

    void InputManager::process_mouse_motion(
            const SDL_MouseMotionEvent *event) {
        if (!event->state) {
            // do not send motion events when no button is pressed
            return;
        }
        if (event->which == SDL_TOUCH_MOUSEID) {
            // simulated from touch events, so it's a duplicate
            return;
        }
        struct ControlMessage msg{};
        if (convert_mouse_motion(event, this->screen, &msg)) {
            if (!this->controller->push_msg(&msg)) {
                LOGW("Could not request 'inject mouse motion event'");
            }
        }
    }

    bool InputManager::convert_touch(const SDL_TouchFingerEvent *from, Screen *screen,
                                     struct ControlMessage *to) {
        to->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;

        if (!convert_touch_action(static_cast<SDL_EventType>(from->type), &to->inject_touch_event.action)) {
            return false;
        }

        struct Size frame_size = screen->frame_size;

        to->inject_touch_event.pointer_id = from->fingerId;
        to->inject_touch_event.position.screen_size = frame_size;
        // SDL touch event coordinates are normalized in the range [0; 1]
        to->inject_touch_event.position.point.x = from->x * static_cast<float>(frame_size.width);
        to->inject_touch_event.position.point.y = from->y * static_cast<float>(frame_size.height);
        to->inject_touch_event.pressure = from->pressure;
        to->inject_touch_event.buttons = static_cast<AndroidMotionEventButtons>(0);
        return true;
    }

    void InputManager::process_touch(
            const SDL_TouchFingerEvent *event) {
        struct ControlMessage msg{};
        if (convert_touch(event, this->screen, &msg)) {
            if (!this->controller->push_msg(&msg)) {
                LOGW("Could not request 'inject touch event'");
            }
        }
    }

    bool InputManager::is_outside_device_screen(int x, int y) {
        return x < 0 || x >= this->screen->frame_size.width ||
               y < 0 || y >= this->screen->frame_size.height;
    }

    bool InputManager::convert_mouse_button(const SDL_MouseButtonEvent *from,
                                            Screen *screen,
                                            struct ControlMessage *to) {
        to->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;

        if (!convert_mouse_action(static_cast<SDL_EventType>(from->type),
                                  &to->inject_touch_event.action)) {
            return false;
        }

        to->inject_touch_event.pointer_id = POINTER_ID_MOUSE;
        to->inject_touch_event.position.screen_size = screen->frame_size;
        to->inject_touch_event.position.point.x = from->x;
        to->inject_touch_event.position.point.y = from->y;
        to->inject_touch_event.pressure = 1.f;
        to->inject_touch_event.buttons =
                convert_mouse_buttons(SDL_BUTTON(from->button));

        return true;
    }

    void InputManager::process_mouse_button(
            const SDL_MouseButtonEvent *event,
            bool control) {
        if (event->which == SDL_TOUCH_MOUSEID) {
            // simulated from touch events, so it's a duplicate
            return;
        }
        if (event->type == SDL_MOUSEBUTTONDOWN) {
            if (control && event->button == SDL_BUTTON_RIGHT) {
                press_back_or_turn_screen_on(this->controller);
                return;
            }
            if (control && event->button == SDL_BUTTON_MIDDLE) {
                action_home(this->controller, ACTION_DOWN | ACTION_UP);
                return;
            }
            // double-click on black borders resize to fit the device screen
            if (event->button == SDL_BUTTON_LEFT && event->clicks == 2) {
                bool outside =
                        this->is_outside_device_screen(event->x, event->y);
                if (outside) {
                    this->screen->resize_to_fit();
                    return;
                }
            }
            // otherwise, send the click event to the device
        }

        if (!control) {
            return;
        }

        struct ControlMessage msg{};
        if (convert_mouse_button(event, this->screen, &msg)) {
            if (!this->controller->push_msg(&msg)) {
                LOGW("Could not request 'inject mouse button event'");
            }
        }
    }

    bool InputManager::convert_mouse_wheel(const SDL_MouseWheelEvent *from,
                                           Screen *screen,
                                           struct ControlMessage *to) {
        struct Position position = {
                .screen_size = screen->frame_size,
                .point = get_mouse_point(screen),
        };

        to->type = CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT;

        to->inject_scroll_event.position = position;
        to->inject_scroll_event.hscroll = from->x;
        to->inject_scroll_event.vscroll = from->y;

        return true;
    }

    void InputManager::process_mouse_wheel(
            const SDL_MouseWheelEvent *event) {
        struct ControlMessage msg{};
        if (convert_mouse_wheel(event, this->screen, &msg)) {
            if (!this->controller->push_msg(&msg)) {
                LOGW("Could not request 'inject mouse wheel event'");
            }
        }
    }

}