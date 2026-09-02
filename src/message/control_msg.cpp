//
// Created by James Shen on 25/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "control_msg.hpp"


#include <cstdio>
#include <ctime>
#include <cassert>

#include <nlohmann/json.hpp>
#include <sys/time.h>
#include <string>

#include "util/buffer_util.hpp"
#include "util/log.hpp"
#include "util/str_util.hpp"


namespace irobot::message
{
    size_t ControlMessage::Serialize(unsigned char* buf)
    {
        buf[0] = (uint8_t)this->type;
        switch (this->type)
        {
        case CONTROL_MSG_TYPE_INJECT_KEYCODE:
            // [type(1)][action(1)][keycode(4)][repeat(4)][metaState(4)] = 14 bytes
            buf[1] = this->inject_keycode.action;
            util::buffer_write32be(&buf[2], this->inject_keycode.keycode);
            util::buffer_write32be(&buf[6], 0); // repeat = 0
            util::buffer_write32be(&buf[10], this->inject_keycode.metastate);
            return 14;
        case CONTROL_MSG_TYPE_INJECT_TEXT:
            {
                // [type(1)][4-byte len][N bytes]
                size_t len = WriteString(this->inject_text.text,
                                         CONTROL_MSG_TEXT_MAX_LENGTH, &buf[1]);
                return 1 + len;
            }
        case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT:
            {
                // [type(1)][action(1)][pointerId(8)][position(12)][pressure(2)][actionButton(4)][buttons(4)] = 32 bytes
                buf[1] = this->inject_touch_event.action;
                util::buffer_write64be(&buf[2], this->inject_touch_event.pointer_id);
                WritePosition(&buf[10], &this->inject_touch_event.position);
                uint16_t pressure = ToFixedPoint16(this->inject_touch_event.pressure);
                util::buffer_write16be(&buf[22], pressure);
                util::buffer_write32be(&buf[24], 0); // actionButton = 0
                util::buffer_write32be(&buf[28], this->inject_touch_event.buttons);
                return 32;
            }
        case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
            // [type(1)][position(12)][hScroll(2)][vScroll(2)][buttons(4)] = 21 bytes
            // Server decodes i16 as float (val/32768) then multiplies by 16.
            // So 1 SDL scroll unit → encode 2048 (= 32768/16) as signed i16.
            WritePosition(&buf[1], &this->inject_scroll_event.position);
            util::buffer_write16be(&buf[13], (uint16_t)(int16_t)(this->inject_scroll_event.hscroll * 2048));
            util::buffer_write16be(&buf[15], (uint16_t)(int16_t)(this->inject_scroll_event.vscroll * 2048));
            util::buffer_write32be(&buf[17], 0); // buttons = 0
            return 21;
        case CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON:
            // [type(1)][action(1)] = 2 bytes
            buf[1] = this->back_or_screen_on.action;
            return 2;
        case CONTROL_MSG_TYPE_SET_CLIPBOARD:
            {
                // [type(1)][sequence(8)][paste(1)][4-byte len][N bytes]
                util::buffer_write64be(&buf[1], 0); // sequence = SEQUENCE_INVALID
                buf[9] = 0; // paste = false
                size_t len = WriteString(this->set_clipboard.text,
                                         CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH,
                                         &buf[10]);
                return 10 + len;
            }
        case CONTROL_MSG_TYPE_GET_CLIPBOARD:
            // [type(1)][copyKey(1)] = 2 bytes
            buf[1] = (uint8_t)this->get_clipboard.copy_key;
            return 2;
        case CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE:
            // [type(1)][on(1)] = 2 bytes; mode NORMAL(2) → on=true, OFF(0) → on=false
            buf[1] = (this->set_screen_power_mode.mode != SCREEN_POWER_MODE_OFF) ? 1 : 0;
            return 2;
        case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL:
        case CONTROL_MSG_TYPE_EXPAND_SETTINGS_PANEL:
        case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL:
        case CONTROL_MSG_TYPE_ROTATE_DEVICE:
            // no additional data
            return 1;
        default:
            LOGW("Unknown message type: %u", (unsigned)this->type);
            return 0;
        }
    }

    std::string ControlMessage::JsonSerialize()
    {
        char buffer[2 * CONTROL_MSG_SERIALIZED_MAX_SIZE];
        char temp[256];
        strcpy(buffer, "{\n");
        sprintf(temp, R"(    "event_time" : ")");
        strcat(buffer, temp);
        timeval tm_now{};
        int milli_seconds;
        gettimeofday(&tm_now, nullptr);
        milli_seconds = (int)lrint(tm_now.tv_usec / 1000.0); // Round to nearest milli seconds
        if (milli_seconds >= 1000)
        {
            // Allow for rounding up to nearest second
            milli_seconds -= 1000;
            tm_now.tv_sec++;
        }
        struct tm* t = localtime(reinterpret_cast<const time_t*>(&tm_now.tv_sec));
        strftime(temp, sizeof(temp) - 1, "%Y-%m-%d %H:%M:%S", t);
        strcat(buffer, temp);
        strcat(buffer, ".");
        sprintf(temp, "%03d", milli_seconds);
        strcat(buffer, temp);
        strcat(buffer, "\",\n");

        switch (this->type)
        {
        case CONTROL_MSG_TYPE_INJECT_KEYCODE:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_KEYCODE");
                strcat(buffer, temp);
                sprintf(temp, "    \"key_code\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"action\" : %d,\n", this->inject_keycode.action);
                strcat(buffer, temp);
                sprintf(temp, "        \"key_code\" : %d,\n", this->inject_keycode.keycode);
                strcat(buffer, temp);
                sprintf(temp, "        \"meta_state\" : %d\n", this->inject_keycode.metastate);
                strcat(buffer, temp);
                strcat(buffer, "    }\n");
            }
            break;
        case CONTROL_MSG_TYPE_INJECT_TEXT:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_TEXT");
                strcat(buffer, temp);
                sprintf(temp, "    \"inject_text\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"text\" : \"%s\"\n", this->inject_text.text);
                strcat(buffer, temp);
                strcat(buffer, "    }\n");
            }
            break;
        case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL");
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL");
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_ROTATE_DEVICE:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_ROTATE_DEVICE");
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_START_RECORDING:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_START_RECORDING");
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_END_RECORDING:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_END_RECORDING");
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON");
                strcat(buffer, temp);
                sprintf(temp, "    \"action\" : %d\n", this->back_or_screen_on.action);
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_GET_CLIPBOARD:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_GET_CLIPBOARD");
                strcat(buffer, temp);
                sprintf(temp, "    \"copy_key\" : %d\n", this->get_clipboard.copy_key);
                strcat(buffer, temp);
            }
            break;
        case CONTROL_MSG_TYPE_SET_CLIPBOARD:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_SET_CLIPBOARD");
                strcat(buffer, temp);
                sprintf(temp, "    \"set_clipboard\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"text\" : \"%s\"\n", this->set_clipboard.text);
                strcat(buffer, temp);
                strcat(buffer, "    }\n");
            }
            break;
        case CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE");
                strcat(buffer, temp);
                sprintf(temp, "    \"mode\" : %d\n", this->set_screen_power_mode.mode);
                strcat(buffer, temp);
            }
            break;

        case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT");
                strcat(buffer, temp);
                sprintf(temp, "    \"touch_event\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"action\" : %d,\n", this->inject_touch_event.action);
                strcat(buffer, temp);
                sprintf(temp, "        \"buttons\" : %d,\n", this->inject_touch_event.buttons);
                strcat(buffer, temp);
                sprintf(temp, "        \"pointer\" : %lld,\n", this->inject_touch_event.pointer_id);
                strcat(buffer, temp);
                sprintf(temp, "        \"pressure\" : %f,\n", this->inject_touch_event.pressure);
                strcat(buffer, temp);
                sprintf(temp, "        \"position\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "            \"screen_size\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"width\" : %d,\n",
                        this->inject_touch_event.position.screen_size.width);
                strcat(buffer, temp);
                sprintf(temp, "                \"height\" : %d\n",
                        this->inject_touch_event.position.screen_size.height);
                strcat(buffer, temp);
                strcat(buffer, "            },\n");
                sprintf(temp, "            \"point\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"x\" : %d,\n", this->inject_touch_event.position.point.x);
                strcat(buffer, temp);
                sprintf(temp, "                \"y\" : %d\n", this->inject_touch_event.position.point.y);
                strcat(buffer, temp);

                strcat(buffer, "            }\n");
                strcat(buffer, "        }\n");
                strcat(buffer, "    }\n");
            }
            break;
        case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
            {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT");
                strcat(buffer, temp);
                sprintf(temp, "    \"scroll_event\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"h_scroll\" : %d,\n", this->inject_scroll_event.hscroll);
                strcat(buffer, temp);
                sprintf(temp, "        \"v_scroll\" : %d,\n", this->inject_scroll_event.vscroll);
                strcat(buffer, temp);
                sprintf(temp, "        \"position\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "            \"screen_size\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"width\" : %d,\n",
                        this->inject_scroll_event.position.screen_size.width);
                strcat(buffer, temp);
                sprintf(temp, "                \"height\" : %d\n",
                        this->inject_scroll_event.position.screen_size.height);
                strcat(buffer, temp);
                strcat(buffer, "            },\n");
                sprintf(temp, "            \"point\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "                \"x\" : %d,\n", this->inject_scroll_event.position.point.x);
                strcat(buffer, temp);
                sprintf(temp, "                \"y\" : %d\n", this->inject_scroll_event.position.point.y);
                strcat(buffer, temp);

                strcat(buffer, "            }\n");
                strcat(buffer, "        }\n");
                strcat(buffer, "    }\n");
            }
            break;
        default:
            // always emit a msg_type, even for types with no dedicated
            // case above (including CONTROL_MSG_TYPE_UNKNOWN itself):
            // JsonDeserialize() requires the key to be present, and a
            // record missing it entirely would crash on replay
            sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_UNKNOWN");
            strcat(buffer, temp);
            break;
        }
        strcat(buffer, "}");
        return buffer;
    }

    size_t ControlMessage::JsonDeserialize(const unsigned char* buf, size_t len)
    {
        size_t ret = 0;
        using nlohmann::json;
        using namespace android;
        std::string content(reinterpret_cast<const char*>(buf), len);
        // A message that is well-formed JSON but the wrong *shape* (e.g. no
        // "msg_type" key, or a type-specific field missing/mistyped) makes
        // nlohmann throw on the j["..."] accesses below. This function runs
        // on the agent-controller thread with no caller-side try/catch, so
        // an uncaught exception here would std::terminate() the whole
        // process. Treat any such shape mismatch the same as invalid JSON:
        // report "could not parse" rather than crashing.
        try
        {
            if (json::accept(content))
            {
                auto j = json::parse(content);
                std::string msg_type = j.value("msg_type", std::string());
                if (msg_type == "CONTROL_MSG_TYPE_INJECT_KEYCODE")
                {
                    this->type = CONTROL_MSG_TYPE_INJECT_KEYCODE;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_INJECT_TEXT")
                {
                    this->type = CONTROL_MSG_TYPE_INJECT_TEXT;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT")
                {
                    this->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT")
                {
                    this->type = CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON")
                {
                    this->type = CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL")
                {
                    this->type = CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL")
                {
                    this->type = CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_GET_CLIPBOARD")
                {
                    this->type = CONTROL_MSG_TYPE_GET_CLIPBOARD;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_SET_CLIPBOARD")
                {
                    this->type = CONTROL_MSG_TYPE_SET_CLIPBOARD;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE")
                {
                    this->type = CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_ROTATE_DEVICE")
                {
                    this->type = CONTROL_MSG_TYPE_ROTATE_DEVICE;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_START_RECORDING")
                {
                    this->type = CONTROL_MSG_TYPE_START_RECORDING;
                }
                else if (msg_type == "CONTROL_MSG_TYPE_END_RECORDING")
                {
                    this->type = CONTROL_MSG_TYPE_END_RECORDING;
                }
                else /* default: */
                {
                    this->type = CONTROL_MSG_TYPE_UNKNOWN;
                }
                ret = len;

                switch (this->type)
                {
                case CONTROL_MSG_TYPE_INJECT_KEYCODE:
                    LOGD("CONTROL_MSG_TYPE_INJECT_KEYCODE: %d", (int)this->type);
                    {
                        auto key_code = j["key_code"];
                        this->inject_keycode.action = (enum AndroidKeyEventAction)key_code["action"];
                        this->inject_keycode.keycode = (enum AndroidKeycode)key_code["key_code"];
                        this->inject_keycode.metastate = (enum AndroidMetaState)key_code["meta_state"];
                    }
                    break;
                case CONTROL_MSG_TYPE_INJECT_TEXT:
                    LOGD("CONTROL_MSG_TYPE_INJECT_TEXT: %d", (int)this->type);
                    {
                        auto inject_text = j["inject_text"];
                        if (inject_text != nullptr)
                        {
                            std::string message = inject_text["text"];
                            int clipboard_len = message.length();
                            char* text = (char*)SDL_malloc(clipboard_len + 1);
                            message.copy(text, clipboard_len);
                            text[clipboard_len] = '\0';
                            this->inject_text.text = text;
                        }
                    }
                    break;
                case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT:
                    LOGD("CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: %d", (int)this->type);
                    {
                        auto touch_event = j["touch_event"];
                        this->inject_touch_event.action = (enum AndroidMotionEventAction)touch_event["action"];
                        this->inject_touch_event.buttons = (enum AndroidMotionEventButtons)touch_event["buttons"];

                        this->inject_touch_event.pointer_id = (int)touch_event["pointer"];
                        this->inject_touch_event.pressure = (float)touch_event["pressure"];
                        auto position = touch_event["position"];
                        auto screen_size = position["screen_size"];
                        this->inject_touch_event.position.screen_size.width = (int)screen_size["width"];
                        this->inject_touch_event.position.screen_size.height = (int)screen_size["height"];

                        auto point = position["point"];
                        this->inject_touch_event.position.point.x = (int)point["x"];
                        this->inject_touch_event.position.point.y = (int)point["y"];
                    }

                    break;
                case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
                    LOGD("CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT: %d", (int)this->type);
                    {
                        auto scroll_event = j["scroll_event"];
                        auto position = scroll_event["position"];
                        auto screen_size = position["screen_size"];
                        this->inject_scroll_event.position.screen_size.width = (int)screen_size["width"];
                        this->inject_scroll_event.position.screen_size.height = (int)screen_size["height"];

                        auto point = position["point"];
                        this->inject_scroll_event.position.point.x = (int)point["x"];
                        this->inject_scroll_event.position.point.y = (int)point["y"];

                        this->inject_scroll_event.hscroll = (int)scroll_event["h_scroll"];
                        this->inject_scroll_event.vscroll = (int)scroll_event["v_scroll"];
                    }

                    break;
                case CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON:
                    LOGD("CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON: %d", (int)this->type);
                    this->back_or_screen_on.action =
                        (enum AndroidKeyEventAction)j.value("action", (int)AKEY_EVENT_ACTION_DOWN);
                    break;
                case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL:
                    LOGD("CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL: %d", (int)this->type);
                    break;
                case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL:
                    LOGD("CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL: %d", (int)this->type);
                    break;
                case CONTROL_MSG_TYPE_GET_CLIPBOARD:
                    LOGD("CONTROL_MSG_TYPE_GET_CLIPBOARD: %d", (int)this->type);
                    this->get_clipboard.copy_key =
                        (enum CopyKey)j.value("copy_key", (int)COPY_KEY_NONE);
                    break;

                case CONTROL_MSG_TYPE_SET_CLIPBOARD:
                    LOGD("CONTROL_MSG_TYPE_SET_CLIPBOARD: %d", (int)this->type);
                    {
                        auto set_clipboard = j.value("set_clipboard", json::object());
                        std::string message = set_clipboard.value("text", std::string());
                        int text_len = message.length();
                        char* text = (char*)SDL_malloc(text_len + 1);
                        message.copy(text, text_len);
                        text[text_len] = '\0';
                        this->set_clipboard.text = text;
                    }
                    break;
                case CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE:
                    LOGD("CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE: %d", (int)this->type);
                    this->set_screen_power_mode.mode =
                        (enum ScreenPowerMode)j.value("mode", (int)SCREEN_POWER_MODE_NORMAL);
                    break;
                case CONTROL_MSG_TYPE_ROTATE_DEVICE:
                    LOGD("CONTROL_MSG_TYPE_ROTATE_DEVICE: %d", (int)this->type);
                    break;
                case CONTROL_MSG_TYPE_START_RECORDING:
                    LOGD("CONTROL_MSG_TYPE_START_RECORDING: %d", (int)this->type);
                    break;
                case CONTROL_MSG_TYPE_END_RECORDING:
                    LOGD("CONTROL_MSG_TYPE_END_RECORDING: %d", (int)this->type);
                    break;
                default:
                    LOGW("Unknown remote control message type: %d", (int)this->type);
                    ret = 0; // error, we cannot recover
                }
            }
        }
        catch (const json::exception& e)
        {
            LOGW("Malformed control message JSON, dropping: %s", e.what());
            this->type = CONTROL_MSG_TYPE_UNKNOWN;
            return 0;
        }

        return ret;
    }

    void ControlMessage::Destroy()
    {
        switch (this->type)
        {
        case CONTROL_MSG_TYPE_INJECT_TEXT:
            SDL_free(this->inject_text.text);
            break;
        case CONTROL_MSG_TYPE_SET_CLIPBOARD:
            SDL_free(this->set_clipboard.text);
            break;
        default:
            // do nothing
            break;
        }
    }


    void ControlMessage::WritePosition(uint8_t* buf, const struct Position* position)
    {
        util::buffer_write32be(&buf[0], position->point.x);
        util::buffer_write32be(&buf[4], position->point.y);
        util::buffer_write16be(&buf[8], position->screen_size.width);
        util::buffer_write16be(&buf[10], position->screen_size.height);
    }

    // write length (4 bytes) + string (non nul-terminated)
    size_t ControlMessage::WriteString(const char* utf8, size_t max_len, unsigned char* buf)
    {
        size_t len = util::utf8_truncation_index(utf8, max_len);
        util::buffer_write32be(buf, (uint32_t)len);
        memcpy(&buf[4], utf8, len);
        return 4 + len;
    }

    uint16_t ControlMessage::ToFixedPoint16(float f)
    {
        assert(f >= 0.0f && f <= 1.0f);
        uint32_t u = f * 0x1p16f; // 2^16
        if (u >= 0xffff)
        {
            u = 0xffff;
        }
        return (uint16_t)u;
    }
}