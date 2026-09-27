# T15 — Let the host skip device messages it doesn't know

Status: open

| | |
|---|---|
| Fixes | [DP14](../gym_data_path_review.md#dp14--new-device-messages-would-break-old-hosts) |
| Priority / size | P0 / S |
| Depends on | T01 |
| Area | C++: `src/message/device_msg.*`, `src/android/receiver.cpp` |
| Needs a device | No |

## Why

The device sends irobot a few message types over the control socket: clipboard text, clipboard
acknowledgement, and UHID output. `DeviceMessage::Deserialize` (`src/message/device_msg.cpp`)
returns `-1` for any other type byte, with the comment "error, we cannot recover", and the receiver
then stops. There's no length field it could use to skip an unknown message.

T16/T17 need a new device message (injection statistics). Version skew is less likely than it
sounds: irobot pushes its own bundled server on every connect, and the server refuses a client whose
version string differs (`Options.parse`). But `build_server.sh` hard-codes
`IROBOT_VERSION_NAME=1.0.0`, so during development a stale server passes that check. Two safety nets
make the new message safe anyway:

- The host will only **ask** for statistics when it can parse them. T17 adds a server option,
  `input_stats=true`, which old servers ignore with a warning (`Options.parse`, `default:` case).
- The host can **skip** any extension subtype it doesn't know (this task).

This task must be merged before, or together with, T17.

## The extension message

A new device message type, `127` (`DEVICE_MSG_TYPE_EXTENSION`), always shaped:

```
[1 byte type = 127][2 bytes subtype, big-endian][4 bytes payload length, big-endian][payload]
```

Because the length is always present, the host can skip any subtype it doesn't understand. Subtype
values are allocated in `device_msg.hpp` with a comment. Reserve `1` for input statistics (T17).

## Steps

1. In `src/message/device_msg.hpp`:
   - add `DEVICE_MSG_TYPE_EXTENSION = 127` to `DeviceMessageType`;
   - add a union member `struct { uint16_t subtype; uint32_t length; unsigned char* payload; }
     extension;` (the payload is owned, freed in `Destroy()`);
   - add `constexpr uint16_t DEVICE_MSG_EXT_INPUT_STATS = 1;`.
2. In `DeviceMessage::Deserialize`, add `case 127`:
   - fewer than 7 bytes available: return 0 (wait for more);
   - read subtype and length; if the full payload isn't there yet, return 0;
   - if the length is larger than a sane maximum (use 1 MiB), log a warning and return -1, since a
     corrupt stream can't be resynchronized;
   - otherwise `SDL_malloc` and copy the payload (allowing length 0), and return `7 + length`.
3. In `DeviceMessage::Destroy()`, free `extension.payload` for this type.
4. In the receiver's message handling (`src/android/receiver.cpp`, the switch around line 31),
   handle `DEVICE_MSG_TYPE_EXTENSION`: for subtype `DEVICE_MSG_EXT_INPUT_STATS`, just log at DEBUG
   for now (T17 does the real handling); for any other subtype, log **once per subtype** at DEBUG
   (`"Ignoring unknown device extension message subtype %u"`) and continue.
5. Improve the existing `default:` log for truly unknown types: `"Unknown device message type %d
   (the device server is probably newer than this irobot; update irobot)"`.

## Tests

Add to a new `tests/test_device_msg.cpp` (tag `[message][device]`):

1. A complete extension message (subtype 1, 5-byte payload) returns 12, and the subtype, length and
   payload are correct. Call `Destroy()` afterwards (run under AddressSanitizer once).
2. A message cut short at 3, 6 and 10 bytes returns 0 each time: "not complete yet", not an error.
3. A zero-length payload returns 7.
4. An unknown subtype (999) followed by a clipboard message in the same buffer: the first
   `Deserialize` returns its full size, and a second `Deserialize` at that offset reads the
   clipboard text correctly. This is what proves unknown subtypes are skippable.
5. The existing clipboard (type 0) and ack (type 1) parsing still works.

## Done when

- The tests pass locally, under AddressSanitizer, and in CI.
- The subtype table in `device_msg.hpp` has a comment saying new subtypes must be added there, and
  that the server may only send type 127 when the host asked for it with a server option (as T17
  does with `input_stats=true`).
