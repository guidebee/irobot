# T17 — Send injection statistics from the device to irobot

Status: open

| | |
|---|---|
| Fixes | [DP06](../gym_data_path_review.md#dp06--injection-results-are-invisible) (device → host) |
| Priority / size | P0 / M |
| Depends on | T15, T16 |
| Area | Java: `DeviceMessage*.java`, `Controller.java`, `Options.java`; C++: `src/core/device_server.cpp`, `src/android/receiver.cpp`, `src/core/controller.*` |
| Needs a device | Yes, for the final check |

## Why

After T16, the device counts every injection outcome, but only its own log shows them. This task
sends the counters to irobot once a second, so irobot can:
- log a readable warning when the device starts rejecting input;
- keep the latest numbers where T18 can hand them to agents.

## Steps

### Server (Java)

1. **Option.** In `Options.java`, add a boolean `inputStats` (default `false`), parsed from
   `input_stats=true|false`, following an existing boolean option such as `send_stream_meta`.
2. **Message.** In `DeviceMessage.java`, add `TYPE_EXTENSION = 127`, a subtype field, and
   `public static DeviceMessage createExtension(int subtype, byte[] payload)`. Add
   `EXT_INPUT_STATS = 1` with a comment pointing to the matching constant in
   `src/message/device_msg.hpp` (from T15).
3. **Writer.** In `DeviceMessageWriter.write`, add the case for `TYPE_EXTENSION`: `writeShort(subtype)`,
   `writeInt(payload.length)`, `write(payload)`. This must match exactly the layout T15 parses.
4. **Sending once a second.** In `Controller`, when `options.getInputStats()` is true, start a small
   daemon thread when the controller starts, and stop it when it stops (look at how `sender` is
   started and stopped around `Controller.java:294-317`). Every 1,000 ms:
   - take `InputStats.INSTANCE.snapshot()`;
   - if it's different from the last one sent, send
     `DeviceMessage.createExtension(EXT_INPUT_STATS, snapshot.toJson().getBytes(UTF_8))` through
     `sender.send(...)`.

   `send` never blocks; it drops the message if the queue is full, which is fine here.

   The JSON also carries `"uptime_ms"` (from `SystemClock.uptimeMillis()`), so the host can tell two
   snapshots apart even if every counter is equal.

### Host (C++)

5. **Request it.** In `src/core/device_server.cpp`, where the server command line is built (the
   `cmd[count++] = ...` lines, around 145–205), add `"input_stats=true"`. Make sure the `cmd` array
   is large enough (check its declared size).
6. **Receive it.** In `src/android/receiver.cpp`, replace T15's DEBUG log for
   `DEVICE_MSG_EXT_INPUT_STATS`: parse the payload with `nlohmann::json` inside `try`/`catch` (a bad
   payload must never crash irobot; log a warning and ignore it), and store it in a small
   thread-safe holder:

   ```cpp
   // src/core/input_stats.hpp
   struct DeviceInputStats
   {
       // Latest raw JSON string from the device, and when it arrived (SDL_GetTicks()).
       std::string json;
       uint32_t received_at_ms = 0;
       uint64_t version = 0;   // increments on every update
   };
   ```

   Guard it with an `SDL_mutex`, and give the `Controller` (which owns the `Receiver`) a getter that
   returns a copy.
7. **Human-readable warning.** When the counters `touch_size_mismatch`, `inject_returned_false`,
   `inject_failed_permission`, `inject_failed_other` or `touch_too_many_pointers` increase from one
   update to the next, log once at WARN with the increases, for example:
   `"Device rejected input in the last second: 12 size mismatch, 0 inject false, ..."`.

## Tests

- **Java** (`DeviceMessageWriterTest.java`, which already exists): writing an extension message with
  subtype 1 and payload `{"a":1}` produces exactly `7F 00 01 00 00 00 07` followed by the payload
  bytes.
- **C++** (`tests/test_device_msg.cpp` from T15): feed those exact bytes (copy them from the Java
  test so both sides are pinned to one layout) through `Deserialize` and the receiver's handling
  path. The holder contains the JSON, and `version` incremented. A malformed JSON payload doesn't
  crash, and leaves the holder unchanged.

## Final device check (required)

1. Build the server (`bash irobot_server/build_server.sh`) and irobot, and connect to a device.
2. Send touches with a wrong screen size: `python tools/agent_client.py interactive --screen-size
   100x100`, and click in the window.
3. irobot's console shows the WARN line with a non-zero `size mismatch` count within about a second.
4. Send correct touches (use the IDE's Test Action). No warning appears.

Paste both console excerpts in the PR.

## Done when

- The tests pass locally and in CI.
- The device check passes.
- Without `input_stats=true` (temporarily remove it), the server sends nothing new. Confirm by
  reading the code path.
