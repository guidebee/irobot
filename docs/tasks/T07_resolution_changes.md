# T07 — Handle resolution changes and announce them

Status: open

| | |
|---|---|
| Fixes | [DP02](../gym_data_path_review.md#dp02--resolution-changes-arent-handled-on-the-agent-path) |
| Priority / size | P0 / M |
| Depends on | T06 |
| Area | C++: `src/agent/agent_manager.cpp`, `src/video/stream.cpp`; docs |
| Needs a device | Yes, for the final check |

## Why

When the device rotates (for example, a landscape game launched from a portrait launcher, which is
exactly what an env reset does), the video stream changes size. Before T06, irobot's agent path
never noticed. After T06, conversion reads the actual decoded frame through `FrameConverter`, whose
cached scaler rebuilds itself, and `SendResolution` reads the actual frame size. So most of the fix
should already be in place.

This task **proves** it end to end, makes the ordering guarantee explicit, and corrects the three
documents that describe rotation handling incorrectly.

The guarantee agents need: **a client always receives the new resolution before (or with) the first
frame of the new size.** Otherwise a client can send a touch sized for the old resolution against
the new stream, and the device drops it silently.

## Steps

1. **Check the ordering in `AgentManager::HandleEvent`.** `SendResolution()` is called before
   `SendOpenCVImage(...)`, and both push onto the same queue in that order, so the resolution
   message goes out first. Confirm this by reading the code, and add a comment stating the
   guarantee so nobody reorders it later.

2. **Resolution messages must survive the frame throttle.** `SendResolution()` runs on every frame
   event, even ones the throttle skips. Keep it that way.

3. **Log size changes once.** In `SendResolution`, when the size differs from
   `last_resolution_width/height` and the old one was non-zero, log at INFO:
   `"Agent video size changed: %dx%d -> %dx%d"`. The session packet in `src/video/stream.cpp:40-46`
   already logs `"Session change: ..."`. Leave that as is; seeing both lines in order is useful when
   debugging.

4. **Correct the docs** that say rotation was already handled:
   - `docs/irobot_gym_ide_design.md` §6.2: the sentence claiming the resolution "picks up a rotation
     automatically since `rgb_frame` changes size". Replace it with what's now true: the resolution
     comes from the decoded frame and is re-announced before the first frame of a new size (T07).
   - `docs/opengym_implementation_plan.md` §4.2: the same claim.
   - `docs/gym_jev_implementation_plan.md` §2, the "Resolution announcement" row: say it's done
     including rotation, referencing T07.

## Tests

Add to `tests/test_agent_frames.cpp`, tagged `[agent][frames][resolution]`:

1. **Resolution before first frame of a new size.** With a loopback video client connected:
   - put a 1200×2670 frame in `rendering_frame`, call `HandleEvent` (`EVENT_NEW_OPENCV_FRAME`);
   - replace it with a 2670×1200 frame, advance past the throttle (set `last_video_send_ticks` back,
     or wait 70 ms), and call `HandleEvent` again.

   Read every message the client received in order. Assert the sequence is: `RESOLUTION 1200×2670`,
   frames of portrait shape, `RESOLUTION 2670×1200`, frames of landscape shape. No landscape frame
   comes before the landscape resolution.
2. **No duplicate announcements.** Two frames of the same size produce one `RESOLUTION` message,
   not two.

## Final device check (required for this task)

1. Start irobot with the phone on its portrait home screen.
2. Run `python tools/agent_client.py stream`. It prints the resolution, portrait.
3. Launch a landscape-only game on the phone.
4. The client prints the new landscape resolution, and the displayed frames are landscape and
   correct: not stretched, not garbage.
5. Rotate back to the home screen. The resolution prints again, portrait.
6. With `irobot_gym_ide` connected, check that touches still land after each rotation (Test an
   action).

Record the device, Android version, and the printed resolutions in the PR.

## Done when

- Both tests pass locally and in CI.
- The device check passes and is written up in the PR.
- The three doc corrections are in the same PR.
