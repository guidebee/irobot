# T10 — Trailing-edge frame throttle and `--agent-max-fps`

Status: open

| | |
|---|---|
| Fixes | [DP09](../gym_data_path_review.md#dp09--leading-edge-throttle) (also covers Jev plan WP0.5) |
| Priority / size | P1 / M |
| Depends on | T06 |
| Area | C++: `src/agent/agent_manager.*`, `src/core/irobot_core.*`, `src/ui/screen.cpp` |
| Needs a device | No |

## Why

Agent frames are sent at most once every 66 ms (`kMinVideoSendIntervalMs`,
`src/agent/agent_manager.cpp:64`). The check (`:384-390`) is **leading-edge**: a frame arriving
within 66 ms of the last send is simply skipped. If the screen then stops changing (a menu finishes
animating, a character stops), the final frame isn't sent until the device's encoder happens to
repeat it about 100 ms later. The agent sees the settled state up to about 166 ms late, and on
devices whose encoder doesn't repeat frames, it may never see it.

The 66 ms is also hard-coded. Training and latency measurement need a faster rate when the host can
afford it, while the IDE is fine at 15 fps.

## Steps

1. **Pure throttle logic first**, so it can be unit-tested without SDL events. Create
   `src/agent/frame_throttle.hpp` (header-only is fine):

   ```cpp
   class FrameThrottle
   {
   public:
       explicit FrameThrottle(uint32_t interval_ms);
       // A new frame arrived at `now`. Returns true if it should be sent immediately.
       // If false, the frame is remembered as pending.
       bool OnFrame(uint32_t now);
       // Returns true if a pending frame is due at `now` (and clears pending).
       bool OnTimer(uint32_t now);
       // Milliseconds until the pending frame is due, or 0 if none is pending.
       uint32_t DelayUntilDue(uint32_t now) const;
       void MarkSent(uint32_t now);
   };
   ```

   `interval_ms == 0` means "no throttling": `OnFrame` always returns true.

2. **Use it in `AgentManager::HandleEvent`.** On `EVENT_NEW_OPENCV_FRAME`:
   - if `OnFrame(now)` is true, send and `MarkSent(now)`;
   - otherwise, if no timer is already scheduled, schedule one with
     `SDL_AddTimer(DelayUntilDue(now), callback, this)`.

   The callback runs on SDL's timer thread, so it must **only** push an SDL event (a new
   `EVENT_AGENT_FRAME_DUE` in `src/ui/events.hpp`) and return 0 (don't repeat). Handle that event in
   `HandleEvent`: if `OnTimer(now)` is true, send the current `rendering_frame` and `MarkSent`.
   Clear the "timer scheduled" flag in both paths. New `AgentManager` members must be public with
   default initializers (see the header's comment about designated initializers).

3. **Make sure the timer subsystem is initialized.** `Screen::InitSDLAndConfigure`
   (`src/ui/screen.cpp:478`) passes `SDL_INIT_VIDEO` or `SDL_INIT_EVENTS`. Add `SDL_INIT_TIMER` to
   `flags` in both cases.

4. **Add the `--agent-max-fps` option**, following exactly how `--max-fps` is done in
   `src/core/irobot_core.cpp`:
   - an `OPT_AGENT_MAX_FPS` constant next to `OPT_MAX_FPS` (line 42);
   - a `long_options` entry (around line 897);
   - a parse case (around line 970), reusing the `ParseMaxFps` style;
   - an `agent_max_fps` field in the options struct (`irobot_core.hpp`) and its default (15);
   - a help text entry next to `--max-fps` (around line 570) saying: *Maximum rate of frames sent to
     agent clients (default 15). 0 means no limit.*

   Pass it into `AgentManager`, where the interval becomes `agent_max_fps ? 1000 / agent_max_fps : 0`.

## Tests

- **`tests/test_frame_throttle.cpp`** (tag `[agent][throttle]`), pure logic with fake times:
  - 15 fps (interval 66): a frame at t=0 is sent; a frame at t=30 is pending; `OnTimer(66)` is due;
    `OnTimer(66)` a second time is not due (it was cleared).
  - Two frames at t=10 and t=20 after a send at t=0 produce exactly one pending send at t=66, not
    two.
  - Interval 0 sends every frame immediately.
- **`tests/test_cli.cpp`**: add a case like the existing `--max-fps 30` one (around line 67):
  `--agent-max-fps 30` sets `agent_max_fps == 30`; the default is 15; an invalid value is rejected.

## Done when

- The tests pass locally and in CI.
- `irobot --help` shows the new option.
- With `tools/agent_client.py stream` running, a short screen animation that stops ends on the final
  image within about 70 ms. Watch the frame numbers from T08 if it has landed, or check by eye.
