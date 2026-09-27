# Gym data path review (2026-09-27)

Status: **review findings; nothing here is fixed yet.** The work to fix them is broken into
junior-sized tasks in [`docs/tasks/`](tasks/README.md).

## Scope

This review covers the code that produces the **raw data a Gym environment (or any agent) consumes**:

- **Observations**: device screen → H.264 → `src/video/stream.cpp` → `src/video/decoder.cpp` →
  `src/ai/brain.cpp` → `src/agent/agent_manager.cpp` → `src/agent/agent_stream.cpp` → the agent
  video port.
- **Actions**: agent control port → `src/agent/agent_controller.cpp` → `src/core/controller.cpp` →
  `irobot_server`'s `control/Controller.java` → `PositionMapper` → `InputManager.injectInputEvent`.
- **The Python clients** that sit on those ports: `tools/agent_client.py`,
  `irobot_gym_ide/connection.py`, and `typesafe_agent/`.
- **Test and CI coverage** of all of the above.

It deliberately does not cover reward design, the env API, or the IDE's authoring features. Those
are in [`gym_jev_implementation_plan.md`](gym_jev_implementation_plan.md) and depend on this data
path being correct first.

Every finding below was checked against the source on `master` at `3e4e081`. Two were confirmed
experimentally (DP03, DP10); how is noted in each. Line numbers are as of that commit.

## Summary

| ID | Severity | Finding | Task(s) |
|---|---|---|---|
| DP01 | **High** | Agents can receive torn frames: the decoder writes the shared RGB frame without holding the lock the agent encoder reads it under | T05, T06 |
| DP02 | **High** | Resolution changes (rotation) break the agent frame path, and the resolution message never reports them. Docs say the opposite | T07, T24 |
| DP03 | **High** | An agent that connects before the first decoded frame crashes irobot (uncaught OpenCV exception) | T04 |
| DP04 | **High** | Frames carry no identity and no usable timestamp: `id` is always 0, and `timestamp` is wall-clock time at encode | T08, T21 |
| DP05 | **High** | Under backpressure the video queue drops the **newest** frame and delivers older ones | T09 |
| DP06 | **High** | Nothing tells an agent whether its touch was actually injected. Every rejection path on the device is silent or verbose-only | T15, T16, T17, T18 |
| DP07 | **High** | Taps have zero hold time (down and up back to back); games that poll touch state per frame can miss them | T12, T22 |
| DP08 | **High** | Releases are sent at (0, 0), so the device lifts the finger at the top-left corner, not where it was | T11 |
| DP09 | Medium | The 66 ms frame throttle is leading-edge only, so the last frame of a transition can be delayed until the encoder's 100 ms repeat | T10 |
| DP10 | Medium | Downscaling uses bilinear filtering, which aliases small objects out of existence; and every decoded frame is colour-converted at full resolution even when no agent needs it | T06 |
| DP11 | Medium | No socket disables Nagle's algorithm, including the one carrying touches to the device | T13 |
| DP12 | Medium | Agent actions are never recorded by Ctrl+E (contrary to the README), and the recording file handle is shared across threads without a lock | T19 |
| DP13 | Medium | Multiple control clients are forwarded unarbitrated and share one pointer-id namespace on the device | T20 |
| DP14 | Medium | An unknown device→host message type is fatal to the host receiver, so new device messages can't be added safely | T15 |
| DP15 | Medium | CI runs **zero** tests: `ctest` finds nothing, and the Python and Java suites aren't run at all | T01, T02, T03 |
| DP16 | Low | `SaveFrame` writes BGR data as RGB (swapped colours); `VideoBuffer` is passed by value | T25 |
| DP17 | Low | "Real, undownscaled device resolution" is actually the video stream's resolution, which differs from the device's with `--max-size` | T24 |
| DP18 | Low | The Python reader thread dies silently, and clients can't tell a fresh frame from a stale one | T21 |
| DP19 | Low | A release sent after a rotation is dropped by `PositionMapper`, leaving a finger stuck down on the device | T14 |
| DP20 | Low | On Windows, `SO_REUSEADDR` lets another process bind the same agent port | T25 |

The open "replay has no effect" bug in
[`irobot_gym_ide_design.md` §13](irobot_gym_ide_design.md#13-replay-raw-reliability-chase-2026-09-12-continued-same-day-after-12s-pause)
is related to several of these: DP06 (no feedback), DP07 (zero-duration taps), DP13 (pointer
clashes). T22 re-runs that investigation once the instruments from T08, T16, T17 and T18 exist.

---

## High severity

### DP01 — Torn frames

**Evidence.** `Decoder::Push` (`src/video/decoder.cpp:146-154`) runs `sws_scale` into
`video_buffer->rgb_frame` and then writes `video_buffer->frame_number`, on the stream thread,
**without** taking `video_buffer->mutex`. `ai::ConvertToMat` (`src/ai/brain.cpp:27-45`) reads
`rgb_frame->data[0]` on the UI/event thread **under** that mutex. The lock only protects the reader
from other readers, not from the writer.

**Impact on the gym.** An observation can contain the top part of frame *N+1* and the bottom part of
frame *N*. For a scrolling game that's a plausible-looking but physically impossible image, and it
also corrupts the perceptual hash used for change detection.

**Fix direction.** Stop keeping a separately-written RGB copy at all: convert agent frames on
demand from the decoded frame, which the lock already protects (T06), after extracting the
conversion into a testable unit (T05).

### DP02 — Resolution changes aren't handled on the agent path

**Evidence.**
- The RGB converter and its buffer are created exactly once, from the first decoded frame
  (`src/video/decoder.cpp:102-143`, guarded by `if (this->sws_cv_ctx == nullptr)`). Nothing ever
  resets `sws_cv_ctx` except `Close()`.
- `rgb_frame->width/height` are set only in that one-time block, so `AgentManager::SendResolution`
  (`src/agent/agent_manager.cpp:330-339`) always reads the first frame's size and never
  re-announces.
- The server sends a session packet with the new size on every resize
  (`src/video/stream.cpp:40-46`); the host logs it and discards it.

**Impact on the gym.**
- After a rotation, `sws_scale` is called with the old dimensions on a frame of the new
  dimensions: at best a garbage image, at worst an out-of-bounds read (when the new frame has fewer
  rows than the old).
- Agents keep sending touches with the old `screen_size`, which `PositionMapper.map()` drops
  silently.
- This is exactly what an env `reset()` does when it launches a landscape game from a portrait
  launcher.

The design docs claim the opposite: `irobot_gym_ide_design.md` §6.2 says the resolution "picks up a
rotation automatically since `rgb_frame` changes size", and `opengym_implementation_plan.md` §4.2 and
`gym_jev_implementation_plan.md` §2 repeat it. Per the code, `rgb_frame` never changes size.

**Fix direction.** Rebuild the converter whenever the decoded frame's size changes and announce the
new size (T07), and correct the docs (T07, T24).

### DP03 — Crash when an agent connects before the first frame

**Evidence.** `AgentStream::AddSession` pushes `EVENT_NEW_OPENCV_FRAME` immediately on connect
(`src/agent/agent_stream.cpp:62-65`). Before any frame is decoded, `rgb_frame` is 0×0 with a null
data pointer. `ConvertToMat` then builds an empty `cv::Mat` and computes `scale = 800 / 0`, and
`cv::resize` on an empty source throws `cv::Exception` (`!ssize.empty()`). Nothing in `src/` catches
it (the only `try` is in `control_msg.cpp`), so the process terminates.

**Confirmed** with OpenCV 5.0's Python binding, which shares the C++ implementation:
`cv2.resize(np.zeros((0, 0, 3), np.uint8), None, fx=inf, fy=inf)` raises
`(-215:Assertion failed) !ssize.empty() in function 'resize'`.

**Impact on the gym.** An env launcher that starts irobot and connects immediately (the natural
thing to do) can kill irobot, or not, depending on timing.

**Fix direction.** Skip encoding until a frame exists (T04).

### DP04 — No frame identity or usable timestamp

**Evidence.** `SendOpenCVImage` sets `msg.id = 0` for every frame and `msg.timestamp` from
`gettimeofday` at *encode* time (`src/agent/agent_manager.cpp:250-254`). The device's presentation
timestamp is parsed from every media packet (`src/video/stream.cpp:76`) and is on the decoded frame,
but it's never forwarded. `video_buffer->frame_number` exists but is only used for a filename.

**Impact on the gym.** A client can't:
- tell a new frame from a repeat;
- count dropped frames;
- pair an `OPENCV_MAT` with the `SCREEN_SHOT` made from the same source frame;
- compute observation age (D1 in the Jev plan);
- measure input-to-screen latency except by guessing from phash changes.

`gettimeofday` is also non-monotonic: it can jump under NTP correction.

**Fix direction.** Put the frame number in `id` (always 0 today, so the change is compatible), and
append a metadata buffer carrying the frame number, device PTS, and monotonic decode and send times
(T08). Existing readers already loop over `count` buffers and only index the first one or two, so an
extra trailing buffer doesn't break them.

### DP05 — Backpressure keeps old frames and drops new ones

**Evidence.** `AgentStream::PushMessage` refuses a new message when its 4-slot queue is full
(`src/agent/agent_stream.cpp:108-130`), and `RunStream` then sends what's queued in FIFO order. Every
connected client shares that one queue, and one slow client can hold the broadcast thread for up to
the 3 s send timeout.

**Impact on the gym.** Exactly when the pipe is under strain, the agent is fed the oldest frames and
the freshest is thrown away. For real-time control that's the wrong policy: a stale observation is
worse than a skipped one.

**Fix direction.** Latest-wins: when full, drop the oldest queued message of the same type (T09).
Per-session queues are a larger change and aren't needed to fix the ordering problem.

### DP06 — Injection results are invisible

**Evidence.**
- `Controller.handleEvent` ignores `injectTouch`'s return value
  (`irobot_server/.../control/Controller.java:356-360`).
- Inside `injectTouch`, a screen-size mismatch is logged only at VERBOSE (`Controller.java:493-500`);
  "too many pointers" logs a warning; and a plain `false` from
  `InputManager.injectInputEvent` (`wrappers/InputManager.java:48-51`) isn't logged at all.
- Injection uses `INJECT_MODE_ASYNC`, so even a `true` only means "queued".
- No device→host message reports any of this, and the agent control port's device→agent direction
  is unused (`AgentController::PushMessage` has no callers).

**Impact on the gym.** When an action has no visible effect, an agent (or a human debugging one)
can't tell "the device ignored my input" from "the game ignored my input". A training run can't count
injection failures, so a bad episode can be blamed on the policy when the pipe dropped its actions.
This is also the reason the §13 bug is so hard to diagnose.

**Fix direction.** Count every outcome on the device, log the silent paths (T16), and carry the
counters to the host and on to agents (T15 makes the host safe to receive new message types; T17
and T18 deliver them).

### DP07 — Zero-duration taps

**Evidence.** A `TAP` sends touch-down and touch-up back to back with no delay
(`irobot_gym_ide/connection.py:213-218`). Both arrive at the device within about a millisecond.

**Impact on the gym.** Many game engines read touch state once per rendered frame (about every
16.7 ms at 60 fps). If both the down and the up land between two polls, the game never sees the
finger at all. The tap is lost with no error anywhere. Event-queue-based input handling doesn't have
this problem, polling does, and an agent can't know which one a given game uses. This is one of the
hypotheses T22 tests for the §13 bug.

**Fix direction.** A minimum hold time for taps (default 50 ms, configurable per project; T12).

### DP08 — Releases land at (0, 0)

**Evidence.** For a `RELEASE` with no position, `connection.py` sends the up event at (0, 0)
(`irobot_gym_ide/connection.py:210-211`). The comment says "the server only reads pointer id +
action", but `injectTouch` calls `pointer.setPoint(point)` for every action, up included
(`Controller.java`, in `injectTouch`), so the device moves the finger to the top-left corner and then
lifts it there.

**Impact on the gym.** Every hold-style action (`*_stop`) releases at the corner. Any UI element that
only activates when the finger is lifted over it won't activate, and a game reading pointer positions
on the release frame sees a touch at the corner.

**Fix direction.** Track each held pointer's last position and release there (T11).

---

## Medium severity

### DP09 — Leading-edge throttle

**Evidence.** Frames are sent only if 66 ms have passed since the last send
(`src/agent/agent_manager.cpp:384-390`). A frame that arrives sooner is skipped, not deferred. If the
screen then stops changing, no new frame arrives until the encoder repeats the last one after 100 ms
(`irobot_server/.../video/SurfaceEncoder.java:32, 322`). The 66 ms interval is also hard-coded.

**Impact on the gym.** The final state after a transition (for example, a menu finishing its
animation) can reach the agent up to about 166 ms late. The repeat behavior also depends on the
device's hardware encoder honoring `KEY_REPEAT_PREVIOUS_FRAME_AFTER`, which varies by vendor.

**Fix direction.** Trailing-edge throttle (send the latest pending frame when the interval expires)
plus an `--agent-max-fps` flag (T10; this also covers Jev plan WP0.5).

### DP10 — Aliased downscaling and wasted conversion

**Evidence.**
- `cv::resize` uses its default bilinear interpolation (`src/ai/brain.cpp:38`) for 3× (800 px) and
  about 11× (240 px) downscales.
- `Decoder::Push` converts every decoded frame to full-resolution BGR (`src/video/decoder.cpp:146`)
  on the stream thread, even when no agent is connected or the throttle is about to discard it.

**Confirmed experimentally.** A 2670×1200 frame containing a 6×6 white square, moved 1 px per frame
across 24 frames and downscaled to 240 px:

| Interpolation | Min / max pixel sum of the square across frames |
|---|---|
| `INTER_LINEAR` (current) | **0** / 48: the object disappears entirely on some frames |
| `INTER_AREA` | 73 / 75: stable |

**Impact on the gym.** Small, fast objects (projectiles, distant enemies) flicker in and out of the
observation, and the thumbnail's phash changes for reasons unrelated to game state. The full-size
conversion costs about 190 megapixels per second at 60 fps on a 2670×1200 device, all of it on the
thread that also feeds the decoder.

**Fix direction.** Convert only when a send is due, directly to the target size, with area averaging
(T06).

### DP11 — Nagle's algorithm is on everywhere

**Evidence.** No `TCP_NODELAY` anywhere in `src/` or in the Python clients. The device control socket
is opened by `net_connect` in `src/core/device_server.cpp:220`. Upstream scrcpy disables Nagle on its
control socket specifically to reduce input latency.

**Impact on the gym.** A tap is two small writes (down, up). With Nagle on, the second can wait for
the first's ACK, and delayed ACK can make that tens of milliseconds or more depending on the OS. That
latency would be invisible in any measurement taken today.

**Fix direction.** Measure, then set `TCP_NODELAY` on the device control socket, the agent sockets,
and the Python clients' control sockets (T13).

### DP12 — Agent actions aren't recorded; recording isn't thread-safe

**Evidence.**
- `AgentManager::ProcessAgentControlMessage` forwards agent messages straight to
  `controller->PushMessage` (`src/agent/agent_manager.cpp:139`), bypassing
  `PushDeviceControlMessage` (`:411-419`), which is the only place that writes to `events.json`. So
  Ctrl+E records human input only, although the README says "every control event — human or agent —
  can be recorded".
- `fp_events` is written by the UI thread (human input) and opened or closed by both the UI thread
  (Ctrl+E) and an agent reader thread (`START/END_RECORDING` messages), with no lock.
- Recorded events have wall-clock times only, with no link to the frame the actor was looking at.

**Impact on the gym.** Agent episodes can't be exported for replay or imitation learning (plan §13),
and starting or stopping a recording while an agent is active is a data race.

**Fix direction.** Record agent messages too, tagged by source and frame number, behind a mutex (T19).

### DP13 — Unarbitrated control clients

**Evidence.** Every connected control client's messages are forwarded (`AgentController` sessions →
`ProcessAgentControlMessage`). Pointer ids are chosen by each client, and the device keeps one
`PointersState` for all of them.

**Impact on the gym.** An IDE connected for monitoring and an env both using pointer 0 overwrite each
other's finger state on the device, producing phantom drags or releases. Two envs accidentally
pointed at one irobot corrupt each other silently.

**Fix direction.** At minimum, report the client count and warn when more than one client injects;
optionally an exclusive mode (T20).

### DP14 — New device messages would break old hosts

**Evidence.** `DeviceMessage::Deserialize` returns `-1` for an unknown type, with the comment "error,
we cannot recover" (`src/message/device_msg.cpp`, `default:` case). The receiver then stops. Device
messages have no generic length field, so an unknown one can't be skipped.

**Impact on the gym.** DP06's fix needs a new device→host message. Shipped naively, a newer
`irobot-server` would silently kill the receiver of an older `irobot`.

**Fix direction.** Teach the host a length-prefixed "extension" message that it can skip when it
doesn't know the subtype, before any new message is sent (T15).

### DP15 — CI runs no tests

**Evidence.**
- The workflow's Test step runs `ctest` (`.github/workflows/build-and-release.yml`), but neither
  `CMakeLists.txt` nor `tests/CMakeLists.txt` calls `enable_testing()` or `add_test()`, so CTest
  finds nothing and passes.
- The Catch2 suite (`tests/`, including the loopback agent tests in `test_agent_reconnect.cpp`)
  never runs in CI.
- The Python suites (`irobot_gym_ide/tests`, 237 tests; `typesafe_agent/tests`) and
  `irobot_server`'s Java unit tests aren't run by any workflow.

**Impact on the gym.** Every fix in this review would land without automated regression protection.

**Fix direction.** Register the C++ tests with CTest (T01), and add Python (T02) and Java (T03) jobs.
Do these first.

---

## Low severity

- **DP16.** `Decoder::SaveFrame` writes the buffer as a PPM, which is RGB, but the buffer holds
  BGR24 (the `sws` target is `AV_PIX_FMT_BGR24` while `rgb_frame->format` is labelled `RGB24`), so
  Ctrl+K captures have swapped red and blue. `ai::SaveFrame` and `ai::ConvertToMat` take
  `VideoBuffer` **by value** (`src/ai/brain.cpp:16, 27`), which copies the struct. It works only
  because every member is a pointer, and it will break the first time a member isn't. (T25)
- **DP17.** `BLOB_MSG_TYPE_RESOLUTION` is described everywhere as the "real, undownscaled device
  resolution". It's the **video stream's** resolution, which is what `PositionMapper` compares
  against, so the behavior is right and the name is wrong. With `--max-size`, touch precision is
  limited to video pixels, which should be documented. (T24)
- **DP18.** `LiveConnection._read_loop` exits silently on any socket error
  (`irobot_gym_ide/connection.py:75-80`), leaving callers reading the last frame forever.
  `latest_frame()` and `latest_thumbnail()` return no frame id, so callers can't detect staleness.
  `typesafe_agent`'s stall counter (`typesafe_agent/runner.py:105`) counts "no new frame arrived" as
  "the screen didn't change". (T21)
- **DP19.** A release sent with the old `screen_size` after a rotation is dropped by
  `PositionMapper.map()`, so the device keeps that finger down indefinitely. The server learns about
  the new display in `Controller.onNewVirtualDisplay` (`Controller.java:167`), which is the natural
  place to lift any fingers still down. (T14)
- **DP20.** On Windows, `SO_REUSEADDR` (`src/platform/net.cpp:78`) allows another process to bind the
  same port. `SO_EXCLUSIVEADDRUSE` is the Windows equivalent of POSIX reuse semantics. The ports are
  loopback-only, which limits the exposure. (T25)

## What's already good

- **Agent sockets bind to loopback only** (`listen_on_port` → `IPV4_LOCALHOST`), so an unauthenticated
  control port isn't exposed to the network.
- **Control framing is length-prefixed**, and oversized frames drop the connection rather than
  stalling.
- **Controller queue ownership is correct**: `Controller::PushMessage` deep-copies the heap strings
  in text and clipboard messages, so the reader thread destroying its copy is safe.
- **Stuck clients can't freeze the stream forever** (3 s send timeout), and a late-joining client gets
  the last resolution immediately.
- **The encoder repeats static frames** every 100 ms and runs with realtime priority and low-latency
  hints, which is the right configuration for an agent.
- **There's a working loopback test harness** (`tests/test_agent_reconnect.cpp`) that new C++ tests
  can copy. It just isn't run by CI (DP15).
