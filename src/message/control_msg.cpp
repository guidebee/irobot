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


namespace irobot::message {

    size_t ControlMessage::Serialize(unsigned char *buf) {
        buf[0] = this->type;
        switch (this->type) {
            case CONTROL_MSG_TYPE_INJECT_KEYCODE:
                buf[1] = this->inject_keycode.action;
                util::buffer_write32be(&buf[2], this->inject_keycode.keycode);
                util::buffer_write32be(&buf[6], this->inject_keycode.metastate);
                return 10;
            case CONTROL_MSG_TYPE_INJECT_TEXT: {
                size_t len = WriteString(this->inject_text.text,
                                         CONTROL_MSG_TEXT_MAX_LENGTH, &buf[1]);
                return 1 + len;
            }
            case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: {
                buf[1] = this->inject_touch_event.action;
                util::buffer_write64be(&buf[2], this->inject_touch_event.pointer_id);
                WritePosition(&buf[10], &this->inject_touch_event.position);
                uint16_t pressure =
                        ToFixedPoint16(this->inject_touch_event.pressure);
                util::buffer_write16be(&buf[22], pressure);
                util::buffer_write32be(&buf[24], this->inject_touch_event.buttons);
                return 28;
            }
            case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
                WritePosition(&buf[1], &this->inject_scroll_event.position);
                util::buffer_write32be(&buf[13],
                                       (uint32_t) this->inject_scroll_event.hscroll);
                util::buffer_write32be(&buf[17],
                                       (uint32_t) this->inject_scroll_event.vscroll);
                return 21;
            case CONTROL_MSG_TYPE_SET_CLIPBOARD: {
                size_t len = WriteString(this->inject_text.text,
                                         CONTROL_MSG_CLIPBOARD_TEXT_MAX_LENGTH,
                                         &buf[1]);
                return 1 + len;
            }
            case CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE:
                buf[1] = this->set_screen_power_mode.mode;
                return 2;
            case CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON:
            case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL:
            case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL:
            case CONTROL_MSG_TYPE_GET_CLIPBOARD:
            case CONTROL_MSG_TYPE_ROTATE_DEVICE:
                // no additional data
                return 1;
            default:
                LOGW("Unknown message type: %u", (unsigned) this->type);
                return 0;
        }
    }

    std::string ControlMessage::JsonSerialize() {
        char buffer[2 * CONTROL_MSG_SERIALIZED_MAX_SIZE];
        char temp[256];
        strcpy(buffer, "{\n");
        sprintf(temp, R"(    "event_time" : ")");
        strcat(buffer, temp);
        timeval tm_now{};
        int milli_seconds;
        gettimeofday(&tm_now, nullptr);
        milli_seconds = (int) lrint(tm_now.tv_usec / 1000.0); // Round to nearest milli seconds
        if (milli_seconds >= 1000) { // Allow for rounding up to nearest second
            milli_seconds -= 1000;
            tm_now.tv_sec++;
        }
        struct tm *t = localtime(reinterpret_cast<const time_t *>(&tm_now.tv_sec));
        strftime(temp, sizeof(temp) - 1, "%Y-%m-%d %H:%M:%S", t);
        strcat(buffer, temp);
        strcat(buffer, ".");
        sprintf(temp, "%03d", milli_seconds);
        strcat(buffer, temp);
        strcat(buffer, "\",\n");

        switch (this->type) {
            case CONTROL_MSG_TYPE_INJECT_KEYCODE: {
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
            case CONTROL_MSG_TYPE_INJECT_TEXT: {
                sprintf(temp, "    \"msg_type\" : \"%s\",\n", "CONTROL_MSG_TYPE_INJECT_TEXT");
                strcat(buffer, temp);
                sprintf(temp, "    \"inject_text\" : {\n");
                strcat(buffer, temp);
                sprintf(temp, "        \"text\" : \"%s\"\n", this->inject_text.text);
                strcat(buffer, temp);
                strcat(buffer, "    }\n");
            }
                break;
            case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL: {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL");
                strcat(buffer, temp);
            }
                break;
            case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL: {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL");
                strcat(buffer, temp);
            }
                break;
            case CONTROL_MSG_TYPE_ROTATE_DEVICE: {
                sprintf(temp, "    \"msg_type\" : \"%s\"\n", "CONTROL_MSG_TYPE_ROTATE_DEVICE");
                strcat(buffer, temp);
            }
                break;

            case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: {
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
            case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT: {

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
                break;

        }
        strcat(buffer, "}");
        return buffer;

    }

    size_t ControlMessage::JsonDeserialize(const unsigned char *buf, size_t len) {
        size_t ret = 0;
        using nlohmann::json;
        using namespace android;
        std::string content(reinterpret_cast<const char *>(buf), len);
        if (json::accept(content)) {
            auto j = json::parse(content);
            std::string msg_type = j["msg_type"];
            if (msg_type == "CONTROL_MSG_TYPE_INJECT_KEYCODE") {
                this->type = CONTROL_MSG_TYPE_INJECT_KEYCODE;
            } else if (msg_type == "CONTROL_MSG_TYPE_INJECT_TEXT") {
                this->type = CONTROL_MSG_TYPE_INJECT_TEXT;
            } else if (msg_type == "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT") {
                this->type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT;
            } else if (msg_type == "CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT") {
                this->type = CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT;
            } else if (msg_type == "CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON") {
                this->type = CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON;
            } else if (msg_type == "CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL") {
                this->type = CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL;
            } else if (msg_type == "CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL") {
                this->type = CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL;
            } else if (msg_type == "CONTROL_MSG_TYPE_GET_CLIPBOARD") {
                this->type = CONTROL_MSG_TYPE_GET_CLIPBOARD;
            } else if (msg_type == "CONTROL_MSG_TYPE_SET_CLIPBOARD") {
                this->type = CONTROL_MSG_TYPE_SET_CLIPBOARD;
            } else if (msg_type == "CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE") {
                this->type = CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE;
            } else if (msg_type == "CONTROL_MSG_TYPE_ROTATE_DEVICE") {
                this->type = CONTROL_MSG_TYPE_ROTATE_DEVICE;
            } else if (msg_type == "CONTROL_MSG_TYPE_START_RECORDING") {
                this->type = CONTROL_MSG_TYPE_START_RECORDING;
            } else if (msg_type == "CONTROL_MSG_TYPE_END_RECORDING") {
                this->type = CONTROL_MSG_TYPE_END_RECORDING;
            } else /* default: */
            {
                this->type = CONTROL_MSG_TYPE_UNKNOWN;
            }
            ret = len;

            switch (this->type) {
                case CONTROL_MSG_TYPE_INJECT_KEYCODE:
                    LOGD("CONTROL_MSG_TYPE_INJECT_KEYCODE: %d", (int) this->type);
                    {
                        auto key_code = j["key_code"];
                        this->inject_keycode.action = (enum AndroidKeyEventAction) key_code["action"];
                        this->inject_keycode.keycode = (enum AndroidKeycode) key_code["key_code"];
                        this->inject_keycode.metastate = (enum AndroidMetaState) key_code["meta_state"];
                    }
                    break;
                case CONTROL_MSG_TYPE_INJECT_TEXT:
                    LOGD("CONTROL_MSG_TYPE_INJECT_TEXT: %d", (int) this->type);
                    {
                        auto inject_text = j["inject_text"];
                        if (inject_text != nullptr) {
                            std::string message = inject_text["text"];
                            int clipboard_len = message.length();
                            char *text = (char *) SDL_malloc(clipboard_len + 1);
                            message.copy(text, clipboard_len);
                            text[clipboard_len] = '\0';
                            this->inject_text.text = text;
                        }
                    }
                    break;
                case CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT:
                    LOGD("CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT: %d", (int) this->type);
                    {
                        auto touch_event = j["touch_event"];
                        this->inject_touch_event.action = (enum AndroidMotionEventAction) touch_event["action"];
                        this->inject_touch_event.buttons = (enum AndroidMotionEventButtons) touch_event["buttons"];

                        this->inject_touch_event.pointer_id = (int) touch_event["pointer"];
                        this->inject_touch_event.pressure = (float) touch_event["pressure"];
                        auto position = touch_event["position"];
                        auto screen_size = position["screen_size"];
                        this->inject_touch_event.position.screen_size.width = (int) screen_size["width"];
                        this->inject_touch_event.position.screen_size.height = (int) screen_size["height"];

                        auto point = position["point"];
                        this->inject_touch_event.position.point.x = (int) point["x"];
                        this->inject_touch_event.position.point.y = (int) point["y"];


                    }

                    break;
                case CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT:
                    LOGD("CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT: %d", (int) this->type);
                    {
                        auto scroll_event = j["scroll_event"];
                        auto position = scroll_event["position"];
                        auto screen_size = position["screen_size"];
                        this->inject_scroll_event.position.screen_size.width = (int) screen_size["width"];
                        this->inject_scroll_event.position.screen_size.height = (int) screen_size["height"];

                        auto point = position["point"];
                        this->inject_scroll_event.position.point.x = (int) point["x"];
                        this->inject_scroll_event.position.point.y = (int) point["y"];

                        this->inject_scroll_event.hscroll = (int) scroll_event["h_scroll"];
                        this->inject_scroll_event.vscroll = (int) scroll_event["v_scroll"];

                    }

                    break;
                case CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON:
                    LOGD("CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL:
                    LOGD("CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL:
                    LOGD("CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_GET_CLIPBOARD:
                    LOGD("CONTROL_MSG_TYPE_GET_CLIPBOARD: %d", (int) this->type);
                    break;

                case CONTROL_MSG_TYPE_SET_CLIPBOARD:
                    LOGD("CONTROL_MSG_TYPE_SET_CLIPBOARD: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE:
                    LOGD("CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_ROTATE_DEVICE:
                    LOGD("CONTROL_MSG_TYPE_ROTATE_DEVICE: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_START_RECORDING:
                    LOGD("CONTROL_MSG_TYPE_START_RECORDING: %d", (int) this->type);
                    break;
                case CONTROL_MSG_TYPE_END_RECORDING:
                    LOGD("CONTROL_MSG_TYPE_END_RECORDING: %d", (int) this->type);
                    break;
                default:
                    LOGW("Unknown remote control message type: %d", (int) this->type);
                    ret = 0; // error, we cannot recover
            }
        }

        return ret;
    }

    void ControlMessage::Destroy() {
        switch (this->type) {
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


    void ControlMessage::WritePosition(uint8_t *buf, const struct Position *position) {
        util::buffer_write32be(&buf[0], position->point.x);
        util::buffer_write32be(&buf[4], position->point.y);
        util::buffer_write16be(&buf[8], position->screen_size.width);
        util::buffer_write16be(&buf[10], position->screen_size.height);
    }

// write length (2 bytes) + string (non nul-terminated)
    size_t ControlMessage::WriteString(const char *utf8, size_t max_len, unsigned char *buf) {
        size_t len = util::utf8_truncation_index(utf8, max_len);
        util::buffer_write16be(buf, (uint16_t) len);
        memcpy(&buf[2], utf8, len);
        return 2 + len;
    }

    uint16_t ControlMessage::ToFixedPoint16(float f) {
        assert(f >= 0.0f && f <= 1.0f);
        uint32_t u = f * 0x1p16f; // 2^16
        if (u >= 0xffff) {
            u = 0xffff;
        }
        return (uint16_t) u;
    }

}