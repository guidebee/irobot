# T23 — Measure end-to-end latency properly

Status: open

| | |
|---|---|
| Fixes | — (a measurement task: it produces the numbers the Gym env's timing is set from) |
| Priority / size | P1 / M |
| Depends on | T08, T10, T13, T21 |
| Area | Python: `typesafe_agent/latency.py` (or a new `tools/latency_probe.py`); docs |
| Needs a device | Yes |

## Why

A Gym env's control period (how often it acts) must be longer than the time an action takes to show
up on screen. Nobody has measured that time for irobot's agent path. The first attempt,
`typesafe_agent latency-check`, times "action sent" to "thumbnail phash changed", which has three
known problems:

- **Resolution:** frames arrive at most every 66 ms (15 fps), so every sample can be off by up to
  66 ms.
- **Wrong cause:** in a scrolling game the screen changes on its own, so a phash change doesn't
  prove the action caused it.
- **No breakdown:** one number, with no way to see where the time goes.

After T08, T10, T13 and T21, all three are fixable.

## Steps

1. **Pick a test screen where the screen is static until you touch it.** A menu button that changes
   when pressed is ideal. Note which screen you used; the method only works if nothing else moves.
2. **Detect change in a region, not the whole frame.** Use the grey `OPENCV_MAT` frame (larger than
   the thumbnail) and compare only a small rectangle around the touched element, with a mean
   absolute difference threshold. Let the user pass the rectangle on the command line (reference
   coordinates, like the IDE's templates), and scale it to the frame size.
3. **Use frame numbers.** Before sending the action, note the latest frame number `N`. The response
   is the first frame numbered greater than `N` (via `wait_for_frame`, T21) whose region differs. That
   removes any chance of timing a frame that was already in flight.
4. **Report a breakdown** for each sample:
   - `total_ms`: from just before the action was sent to when the changed frame was received
     (client monotonic clock);
   - `irobot_pipeline_ms`: that frame's `age_at_send_us / 1000` (decode → queued, inside irobot);
   - `device_and_transport_ms`: `total_ms - irobot_pipeline_ms`. This covers everything else: input
     path to the device, the game reacting, rendering, encoding and transfer.
5. **Run each configuration 50 times** and report p50, p95 and max:
   - `--agent-max-fps 15` (default) versus `30` versus `0` (T10);
   - USB versus Wi-Fi, if you have both.

   Always record the device model, Android version, irobot flags, and the git commit.
6. **Write the results** to `docs/measurements/latency.md`: a short method section (steps 1–4), then
   one table per device. Link it from `docs/gym_jev_implementation_plan.md` WP0.3, and say there
   which control period the numbers suggest (at least the p95 `total_ms`, rounded up).

## Tests

The measurement needs a device, but the calculation doesn't. Unit-test the pieces with a fake
connection: region-difference detection (identical region → no change; a changed square → change),
"first frame newer than N" selection, and the breakdown arithmetic.

## Done when

- The unit tests pass locally and in CI.
- `docs/measurements/latency.md` has numbers for at least one physical device, at 15 and 30 agent
  fps, and ideally one emulator.
- The Jev plan's WP0.3 links to it and states the suggested control period.
