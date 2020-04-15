//
// Created by James Shen on 28/3/20.
// Copyright (c) 2020 GUIDEBEE IT. All rights reserved
//

#include "catch.hpp"
#include <cstring>

#include "message/control_msg.hpp"
#include "message/device_msg.hpp"
#include <nlohmann/json.hpp>
#include <iostream>


using nlohmann::json;
using namespace irobot::message;

TEST_CASE("serialize inject keycode", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_KEYCODE,
            .inject_keycode = {
                    .action = AKEY_EVENT_ACTION_UP,
                    .keycode = AKEYCODE_ENTER,
                    .metastate = static_cast<enum AndroidMetaState>(AMETA_SHIFT_ON
                                                                    | AMETA_SHIFT_LEFT_ON),
            },
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 10);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_INJECT_KEYCODE,
            0x01, // AKEY_EVENT_ACTION_UP
            0x00, 0x00, 0x00, 0x42, // AKEYCODE_ENTER
            0x00, 0x00, 0x00, 0x41, // AMETA_SHIFT_ON | AMETA_SHIFT_LEFT_ON
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("json serialize inject keycode", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_KEYCODE,
            .inject_keycode = {
                    .action = AKEY_EVENT_ACTION_UP,
                    .keycode = AKEYCODE_ENTER,
                    .metastate = static_cast<enum AndroidMetaState>(AMETA_SHIFT_ON
                                                                    | AMETA_SHIFT_LEFT_ON),
            },
    };

    auto json_str = msg.JsonSerialize();
    REQUIRE(json::accept(json_str));
    json j = json::parse(json_str);
    auto msg_type = j["msg_type"];

    REQUIRE(msg_type == "CONTROL_MSG_TYPE_INJECT_KEYCODE");
    char cstr[json_str.size() + 1];
    strcpy(cstr, json_str.c_str());
    struct ControlMessage msg1{};
    msg1.JsonDeserialize((const unsigned char *) cstr, strlen(cstr));
    REQUIRE(msg1.type == CONTROL_MSG_TYPE_INJECT_KEYCODE);
    REQUIRE(msg1.inject_keycode.action == AKEY_EVENT_ACTION_UP);
    REQUIRE(msg1.inject_keycode.keycode == AKEYCODE_ENTER);
    REQUIRE(msg1.inject_keycode.metastate == static_cast<enum AndroidMetaState>(AMETA_SHIFT_ON
                                                                                | AMETA_SHIFT_LEFT_ON));
}


TEST_CASE("serialize inject text", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_TEXT,
            .inject_text = {
                    .text = const_cast<char *>("hello, world!"),
            },
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 16);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_INJECT_TEXT,
            0x00, 0x0d, // text length
            'h', 'e', 'l', 'l', 'o', ',', ' ', 'w', 'o', 'r', 'l', 'd', '!', // text
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize inject text long", "[message][ControlMessage]") {
    struct ControlMessage msg{};
    msg.type = CONTROL_MSG_TYPE_INJECT_TEXT;
    char text[CONTROL_MSG_TEXT_MAX_LENGTH + 1];
    memset(text, 'a', sizeof(text));
    text[CONTROL_MSG_TEXT_MAX_LENGTH] = '\0';
    msg.inject_text.text = text;

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 3 + CONTROL_MSG_TEXT_MAX_LENGTH);

    unsigned char expected[3 + CONTROL_MSG_TEXT_MAX_LENGTH];
    expected[0] = CONTROL_MSG_TYPE_INJECT_TEXT;
    expected[1] = 0x01;
    expected[2] = 0x2c; // text length (16 bits)
    memset(&expected[3], 'a', CONTROL_MSG_TEXT_MAX_LENGTH);

    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize inject touch event", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
            .inject_touch_event = {
                    .action = AMOTION_EVENT_ACTION_DOWN,
                    .buttons = AMOTION_EVENT_BUTTON_PRIMARY,
                    .pointer_id = 0x1234567887654321L,
                    .position = {
                            .screen_size = {
                                    .width = 1080,
                                    .height = 1920,
                            },
                            .point = {
                                    .x = 100,
                                    .y = 200,
                            },

                    },
                    .pressure = 1.0f,

            },
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 28);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
            0x00, // AKEY_EVENT_ACTION_DOWN
            0x12, 0x34, 0x56, 0x78, 0x87, 0x65, 0x43, 0x21, // pointer id
            0x00, 0x00, 0x00, 0x64, 0x00, 0x00, 0x00, 0xc8, // 100 200
            0x04, 0x38, 0x07, 0x80, // 1080 1920
            0xff, 0xff, // pressure
            0x00, 0x00, 0x00, 0x01 // AMOTION_EVENT_BUTTON_PRIMARY
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}


TEST_CASE("json serialize inject touch event", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
            .inject_touch_event = {
                    .action = AMOTION_EVENT_ACTION_DOWN,
                    .buttons = AMOTION_EVENT_BUTTON_PRIMARY,
                    .pointer_id = 0x1234567887654321L,
                    .position = {
                            .screen_size = {
                                    .width = 1080,
                                    .height = 1920,
                            },
                            .point = {
                                    .x = 100,
                                    .y = 200,
                            },

                    },
                    .pressure = 1.0f,

            },
    };

    auto json_str = msg.JsonSerialize();
    REQUIRE(json::accept(json_str));
    json j = json::parse(json_str);
    auto msg_type = j["msg_type"];
    REQUIRE(msg_type == "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT");

}

TEST_CASE("json serialize inject scroll event", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT,
            .inject_scroll_event = {
                    .position = {
                            .screen_size = {
                                    .width = 1080,
                                    .height = 1920,
                            },
                            .point = {
                                    .x = 260,
                                    .y = 1026,
                            },

                    },
                    .hscroll = 1,
                    .vscroll = -1,
            },
    };

    auto json_str = msg.JsonSerialize();
    REQUIRE(json::accept(json_str));
    json j = json::parse(json_str);
    std::string msg_type = j["msg_type"];
    REQUIRE(msg_type == "CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT");
    char cstr[json_str.size() + 1];
    strcpy(cstr, json_str.c_str());
    struct ControlMessage msg1{};
    msg1.JsonDeserialize((const unsigned char *) cstr, strlen(cstr));
    REQUIRE(msg1.type == CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT);
    REQUIRE(msg1.inject_scroll_event.position.point.x == 260);
    REQUIRE(msg1.inject_scroll_event.position.point.y == 1026);
    REQUIRE(msg1.inject_scroll_event.position.screen_size.width == 1080);
    REQUIRE(msg1.inject_scroll_event.position.screen_size.height == 1920);
    auto content = msg1.JsonSerialize();
    REQUIRE(json::accept(content));
    json j2 = json::parse(content);
    std::cout << j2.dump(2);


}


TEST_CASE("serialize inject scroll event", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT,
            .inject_scroll_event = {
                    .position = {
                            .screen_size = {
                                    .width = 1080,
                                    .height = 1920,
                            },
                            .point = {
                                    .x = 260,
                                    .y = 1026,
                            },

                    },
                    .hscroll = 1,
                    .vscroll = -1,
            },
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 21);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT,
            0x00, 0x00, 0x01, 0x04, 0x00, 0x00, 0x04, 0x02, // 260 1026
            0x04, 0x38, 0x07, 0x80, // 1080 1920
            0x00, 0x00, 0x00, 0x01, // 1
            0xFF, 0xFF, 0xFF, 0xFF, // -1
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize back or screen on", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON,
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 1);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON,
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize expand notification panel", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL,
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 1);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL,
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize collapse notification panel", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL,
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 1);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL,
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize get clipboard", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_GET_CLIPBOARD,
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 1);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_GET_CLIPBOARD,
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize set clipboard", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_SET_CLIPBOARD,
            .inject_text = {
                    .text = const_cast<char *>("hello, world!"),
            },
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 16);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_SET_CLIPBOARD,
            0x00, 0x0d, // text length
            'h', 'e', 'l', 'l', 'o', ',', ' ', 'w', 'o', 'r', 'l', 'd', '!', // text
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize set screen power mode", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE,
            .set_screen_power_mode = {
                    .mode = SCREEN_POWER_MODE_NORMAL,
            },
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 2);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE,
            0x02, // SCREEN_POWER_MODE_NORMAL
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("serialize rotate device", "[message][ControlMessage]") {
    struct ControlMessage msg = {
            .type = CONTROL_MSG_TYPE_ROTATE_DEVICE,
    };

    unsigned char buf[CONTROL_MSG_SERIALIZED_MAX_SIZE];
    int size = msg.Serialize(buf);
    REQUIRE(size == 1);

    const unsigned char expected[] = {
            CONTROL_MSG_TYPE_ROTATE_DEVICE,
    };
    REQUIRE(!memcmp(buf, expected, sizeof(expected)));
}

TEST_CASE("deserialize clipboard", "[message][ControlMessage]") {
    const unsigned char input[] = {
            DEVICE_MSG_TYPE_CLIPBOARD,
            0x00, 0x03, // text length
            0x41, 0x42, 0x43, // "ABC"
    };

    struct DeviceMessage msg{};
    ssize_t r = msg.Deserialize(input, sizeof(input));
    REQUIRE(r == 6);

    REQUIRE(msg.type == DEVICE_MSG_TYPE_CLIPBOARD);
    REQUIRE(msg.clipboard.text);
    REQUIRE(!strcmp("ABC", msg.clipboard.text));

    msg.Destroy();
}


