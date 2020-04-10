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
#include "video/video_buffer.hpp"
#include "message/control_msg.hpp"

namespace irobot::ui {

    static const int ACTION_DOWN = 1;
    static const int ACTION_UP = 1 << 1;

// Convert window coordinates (as provided by SDL_GetMouseState() to renderer
// coordinates (as provided in SDL mouse events)
//
// See my question:
// <https://stackoverflow.com/questions/49111054/how-to-get-mouse-position-on-mouse-wheel-event>
    void InputManager::ConvertToRendererCoordinates(SDL_Renderer *renderer,
                                                    int *x, int *y) {
        SDL_Rect viewport;
        float scale_x, scale_y;
        SDL_RenderGetViewport(renderer, &viewport);
        SDL_RenderGetScale(renderer, &scale_x, &scale_y);
        *x = (int) (static_cast<float>(*x) / scale_x) - viewport.x;
        *y = (int) (static_cast<float>(*y) / scale_y) - viewport.y;
    }

    struct Point InputManager::GetMousePoint(Screen *screen) {
        int x;
        int y;
        SDL_GetMouseState(&x, &y);
        ConvertToRendererCoordinates(screen->renderer, &x, &y);
        return (struct Point) {
                .x = x,
                .y = y,
        };
    }


    void InputManager::SendKeycode(enum AndroidKeycode keycode,
                                   int actions, const char *name) {
        // send DOWN event
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_INJECT_KEYCODE;
        msg.inject_keycode.keycode = keycode;
        msg.inject_keycode.metastate = static_cast<AndroidMetaState>(0);

        if (actions & ACTION_DOWN) {
            msg.inject_keycode.action = AKEY_EVENT_ACTION_DOWN;
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject %s (DOWN)'", name);
                return;
            }
        }

        if (actions & ACTION_UP) {
            msg.inject_keycode.action = AKEY_EVENT_ACTION_UP;
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject %s (UP)'", name);
            }
        }
    }


// turn the screen on if it was off, press BACK otherwise
    void InputManager::PressBackOrTurnScreenOn() {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON;

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            LOGW("Could not request 'press back or turn screen on'");
        }
    }

    void InputManager::ExpandNotificationPanel() {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL;

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            LOGW("Could not request 'expand notification panel'");
        }
    }

    void InputManager::CollapseNotificationPanel() {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL;

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            LOGW("Could not request 'collapse notification panel'");
        }
    }

    void InputManager::RequestDeviceClipboard() {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_GET_CLIPBOARD;

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            LOGW("Could not request device clipboard");
        }
    }

    void InputManager::SetDeviceClipboard() {
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

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            SDL_free(text);
            LOGW("Could not request 'set device clipboard'");
        }
    }

    void InputManager::SetScreenPowerMode(
            enum ScreenPowerMode mode) {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE;
        msg.set_screen_power_mode.mode = mode;

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            LOGW("Could not request 'set screen power mode'");
        }
    }

    void InputManager::SwitchFpsCounterState(video::FpsCounter *fps_counter) {
        // the started state can only be written from the current thread, so there
        // is no ToCToU issue
        if (fps_counter->IsStarted()) {
            fps_counter->Stop();
            LOGI("FPS counter stopped");
        } else {
            if (fps_counter->Start()) {
                LOGI("FPS counter started");
            } else {
                LOGE("FPS counter starting failed");
            }
        }
    }

    void InputManager::PasteClipboard() {
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
        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            SDL_free(text);
            LOGW("Could not request 'paste clipboard'");
        }
    }

    void InputManager::RotateDevice() {
        struct ControlMessage msg{};
        msg.type = CONTROL_MSG_TYPE_ROTATE_DEVICE;

        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            LOGW("Could not request device rotation");
        }
    }

    void InputManager::ProcessTextInput(
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
        if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
            SDL_free(msg.inject_text.text);
            LOGW("Could not request 'inject text'");
        }
    }

    bool InputManager::ConvertInputKey(const SDL_KeyboardEvent *from,
                                       struct ControlMessage *to,
                                       bool prefer_text) {
        to->type = CONTROL_MSG_TYPE_INJECT_KEYCODE;

        if (!ConvertKeycodeAction(static_cast<SDL_EventType>(from->type), &to->inject_keycode.action)) {
            return false;
        }

        uint16_t mod = from->keysym.mod;
        if (!ConvertKeycode(from->keysym.sym, &to->inject_keycode.keycode, mod,
                            prefer_text)) {
            return false;
        }

        to->inject_keycode.metastate = ConvertMetaState(static_cast<SDL_Keymod>(mod));

        return true;
    }

    void InputManager::ProcessKey(
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
                        ActionHome(action);
                    }
                    return;
                case SDLK_b: // fall-through
                case SDLK_BACKSPACE:
                    if (control && cmd && !shift && !repeat) {
                        ActionBack(action);
                    }
                    return;
                case SDLK_s:
                    if (control && cmd && !shift && !repeat) {
                        ActionAppSwitch(action);
                    }
                    return;
                case SDLK_m:
                    // Ctrl+m on all platform, since Cmd+m is already captured by
                    // the system on macOS to minimize the window
                    if (control && ctrl && !meta && !shift && !repeat) {
                        ActionMenu(action);
                    }
                    return;
                case SDLK_p:
                    if (control && cmd && !shift && !repeat) {
                        ActionPower(action);
                    }
                    return;
                case SDLK_o:
                    if (control && cmd && !shift && down) {
                        SetScreenPowerMode(SCREEN_POWER_MODE_OFF);
                    }
                    return;
                case SDLK_DOWN:
                    if (control && cmd && !shift) {
                        // forward repeated events
                        ActionVolumeDown(action);
                    }
                    return;
                case SDLK_UP:
                    if (control && cmd && !shift) {
                        // forward repeated events
                        ActionVolumeUp(action);
                    }
                    return;
                case SDLK_c:
                    if (control && cmd && !shift && !repeat && down) {
                        RequestDeviceClipboard();
                    }
                    return;
                case SDLK_v:
                    if (control && cmd && !repeat && down) {
                        if (shift) {
                            // store the text in the device clipboard
                            SetDeviceClipboard();
                        } else {
                            // inject the text as input events
                            PasteClipboard();
                        }
                    }
                    return;
                case SDLK_f:
                    if (!shift && cmd && !repeat && down) {
                        this->screen->SwitchFullscreen();
                    }
                    return;
                case SDLK_x:
                    if (!shift && cmd && !repeat && down) {
                        this->screen->ResizeToFit();
                    }
                    return;
                case SDLK_g:
                    if (!shift && cmd && !repeat && down) {
                        this->screen->ResizeToPixelPerfect();
                    }
                    return;
                case SDLK_i:
                    if (!shift && cmd && !repeat && down) {
                        struct video::FpsCounter *fps_counter =
                                this->null_input_manager->video_buffer->fps_counter;
                        SwitchFpsCounterState(fps_counter);
                    }
                    return;
                case SDLK_n:
                    if (control && cmd && !repeat && down) {
                        if (shift) {
                            CollapseNotificationPanel();
                        } else {
                            ExpandNotificationPanel();
                        }
                    }
                    return;
                case SDLK_r:
                    if (control && cmd && !shift && !repeat && down) {
                        RotateDevice();
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
        if (ConvertInputKey(event, &msg, this->prefer_text)) {
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject keycode'");
            }
        }
    }

    bool InputManager::ConvertMouseMotion(const SDL_MouseMotionEvent *from,
                                          Screen *screen,
                                          struct ControlMessage *to) {
        to->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;
        to->inject_touch_event.action = AMOTION_EVENT_ACTION_MOVE;
        to->inject_touch_event.pointer_id = POINTER_ID_MOUSE;
        to->inject_touch_event.position.screen_size = screen->frame_size;
        to->inject_touch_event.position.point.x = from->x;
        to->inject_touch_event.position.point.y = from->y;
        to->inject_touch_event.pressure = 1.f;
        to->inject_touch_event.buttons = ConvertMouseButtons(from->state);

        return true;
    }

    void InputManager::ProcessMouseMotion(
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
        if (ConvertMouseMotion(event, this->screen, &msg)) {
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject mouse motion event'");
            }
        }
    }

    bool InputManager::ConvertTouch(const SDL_TouchFingerEvent *from, Screen *screen,
                                    struct ControlMessage *to) {
        to->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;

        if (!ConvertTouchAction(static_cast<SDL_EventType>(from->type), &to->inject_touch_event.action)) {
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

    void InputManager::ProcessTouch(
            const SDL_TouchFingerEvent *event) {
        struct ControlMessage msg{};
        if (ConvertTouch(event, this->screen, &msg)) {
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject touch event'");
            }
        }
    }

    bool InputManager::IsOutsideDeviceScreen(int x, int y) {
        return x < 0 || x >= this->screen->frame_size.width ||
               y < 0 || y >= this->screen->frame_size.height;
    }

    bool InputManager::ConvertMouseButton(const SDL_MouseButtonEvent *from,
                                          Screen *screen,
                                          struct ControlMessage *to) {
        to->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;

        if (!ConvertMouseAction(static_cast<SDL_EventType>(from->type),
                                &to->inject_touch_event.action)) {
            return false;
        }

        to->inject_touch_event.pointer_id = POINTER_ID_MOUSE;
        to->inject_touch_event.position.screen_size = screen->frame_size;
        to->inject_touch_event.position.point.x = from->x;
        to->inject_touch_event.position.point.y = from->y;
        to->inject_touch_event.pressure = 1.f;
        to->inject_touch_event.buttons =
                ConvertMouseButtons(SDL_BUTTON(from->button));

        return true;
    }

    void InputManager::ProcessMouseButton(
            const SDL_MouseButtonEvent *event,
            bool control) {
        if (event->which == SDL_TOUCH_MOUSEID) {
            // simulated from touch events, so it's a duplicate
            return;
        }
        if (event->type == SDL_MOUSEBUTTONDOWN) {
            if (control && event->button == SDL_BUTTON_RIGHT) {
                PressBackOrTurnScreenOn();
                return;
            }
            if (control && event->button == SDL_BUTTON_MIDDLE) {
                ActionHome(ACTION_DOWN | ACTION_UP);
                return;
            }
            // double-click on black borders resize to fit the device screen
            if (event->button == SDL_BUTTON_LEFT && event->clicks == 2) {
                bool outside =
                        this->IsOutsideDeviceScreen(event->x, event->y);
                if (outside) {
                    this->screen->ResizeToFit();
                    return;
                }
            }
            // otherwise, send the click event to the device
        }

        if (!control) {
            return;
        }

        struct ControlMessage msg{};
        if (ConvertMouseButton(event, this->screen, &msg)) {
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject mouse button event'");
            }
        }
    }

    bool InputManager::ConvertMouseWheel(const SDL_MouseWheelEvent *from,
                                         Screen *screen,
                                         struct ControlMessage *to) {
        struct Position position = {
                .screen_size = screen->frame_size,
                .point = GetMousePoint(screen),
        };

        to->type = CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT;

        to->inject_scroll_event.position = position;
        to->inject_scroll_event.hscroll = from->x;
        to->inject_scroll_event.vscroll = from->y;

        return true;
    }

    void InputManager::ProcessMouseWheel(
            const SDL_MouseWheelEvent *event) {
        struct ControlMessage msg{};
        if (ConvertMouseWheel(event, this->screen, &msg)) {
            if (!this->null_input_manager->PushDeviceControlMessage(&msg)) {
                LOGW("Could not request 'inject mouse wheel event'");
            }
        }
    }

    bool InputManager::IsApk(const char *file) {
        const char *ext = strrchr(file, '.');
        return ext && !strcmp(ext, ".apk");
    }

#if defined(__APPLE__) || defined(__WINDOWS__)
# define CONTINUOUS_RESIZING_WORKAROUND
#endif

#ifdef CONTINUOUS_RESIZING_WORKAROUND

// On Windows and MacOS, resizing blocks the event loop, so resizing events are
// not triggered. As a workaround, handle them in an event handler.
//
// <https://bugzilla.libsdl.org/show_bug.cgi?id=2077>
// <https://stackoverflow.com/a/40693139/1987178>
    int InputManager::EventWatcher(void *data, SDL_Event *event) {
        auto *input_manager = (ui::InputManager *) data;
        if (event->type == SDL_WINDOWEVENT
            && event->window.event == SDL_WINDOWEVENT_RESIZED) {
            // called from another thread, not very safe, but it's a workaround!
            input_manager->screen->Render();
        }
        return 0;
    }

#endif

    enum EventResult InputManager::HandleEvent(SDL_Event *event, bool control) {
        switch (event->type) {
            case EVENT_STREAM_STOPPED:
            case SDL_QUIT:
            case EVENT_NEW_OPENCV_FRAME:
                return this->null_input_manager->HandleEvent(event, true);
                break;
            case EVENT_NEW_FRAME:
                if (!this->screen->has_frame) {
                    this->screen->has_frame = true;
                    // this is the very first frame, show the window
                    this->screen->ShowWindow();
                }
                if (!this->screen->UpdateFrame(this->null_input_manager->video_buffer)) {
                    return EVENT_RESULT_CONTINUE;
                }
                break;

            case SDL_WINDOWEVENT:
                this->screen->HandleWindowEvent(&event->window);
                break;
            case SDL_TEXTINPUT:
                if (!control) {
                    break;
                }
                this->ProcessTextInput(&event->text);
                break;
            case SDL_KEYDOWN:
            case SDL_KEYUP:
                // some key events do not interact with the device, so process the
                // event even if control is disabled
                this->ProcessKey(&event->key, control);
                break;
            case SDL_MOUSEMOTION:
                if (!control) {
                    break;
                }
                this->ProcessMouseMotion(&event->motion);
                break;
            case SDL_MOUSEWHEEL:
                if (!control) {
                    break;
                }
                this->ProcessMouseWheel(&event->wheel);
                break;
            case SDL_MOUSEBUTTONDOWN:
            case SDL_MOUSEBUTTONUP:
                // some mouse events do not interact with the device, so process
                // the event even if control is disabled
                this->ProcessMouseButton(&event->button,
                                         control);
                break;
            case SDL_FINGERMOTION:
            case SDL_FINGERDOWN:
            case SDL_FINGERUP:
                this->ProcessTouch(&event->tfinger);
                break;
            case SDL_DROPFILE: {
                if (!control) {
                    break;
                }
                FileHandlerActionType action;
                if (IsApk(event->drop.file)) {
                    action = ACTION_INSTALL_APK;
                } else {
                    action = ACTION_PUSH_FILE;
                }
                if (this->screen->file_handler != nullptr) {
                    this->screen->file_handler->Request(action, event->drop.file);
                }
                break;
            }
        }
        return EVENT_RESULT_CONTINUE;
    }

    bool InputManager::EventLoop(bool display, bool control) {
#ifdef CONTINUOUS_RESIZING_WORKAROUND
        if (display) {
            SDL_AddEventWatch(EventWatcher, this);
        }
#endif
        SDL_Event event;
        while (SDL_WaitEvent(&event)) {
            enum EventResult result = this->HandleEvent(&event, control);
            switch (result) {
                case EVENT_RESULT_STOPPED_BY_USER:
                    return true;
                case EVENT_RESULT_STOPPED_BY_EOS:
                    LOGW("Device disconnected");
                    return false;
                case EVENT_RESULT_CONTINUE:
                    break;
            }
        }
        return false;
    }


}
