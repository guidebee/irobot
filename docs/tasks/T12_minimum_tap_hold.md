# T12 — Give taps a minimum hold time

Status: open

| | |
|---|---|
| Fixes | [DP07](../gym_data_path_review.md#dp07--zero-duration-taps) |
| Priority / size | P0 / S |
| Depends on | T02 |
| Area | Python: `irobot_gym_ide/connection.py`, `model.py`, `io.py` and tests |
| Needs a device | No (the effect on real games is checked in T22) |

## Why

A `TAP` event sends touch-down and touch-up back to back (`irobot_gym_ide/connection.py:213-218`),
so both reach the device within about a millisecond. Many games read touch state once per rendered
frame (every 16.7 ms at 60 fps). If the down and the up both happen between two reads, the game
never sees the tap. Nothing reports an error, because from the device's point of view both events
were delivered fine. An agent can't know how a particular game reads input, so taps need to last
long enough for any game to see them.

## Steps

1. **Add a project setting.** In `irobot_gym_ide/model.py`, add `tap_hold_ms: int = 50` to
   `Project`, next to `time_scale`, with a one-line comment saying why the default is 50: about three
   frames at 60 fps, long enough for per-frame polling, short enough to still read as a tap.
   - Make `to_dict()` and `from_dict()` handle it. Missing in an old `project.yaml` means 50.
   - Add it to the metadata keys `io.py` writes to `project.yaml` (look for `_META_KEYS`).
2. **Use it in `LiveConnection`.** Add a `tap_hold_ms = 50` attribute, synced from the project the
   same way `time_scale` is. Search `gui/main_window.py` for where `time_scale` gets copied from the
   project to the connection, and copy `tap_hold_ms` in the same place.
   `typesafe_agent/runner.py` creates its own `LiveConnection` and currently copies **neither**
   setting, which is a bug. Copy both `time_scale` and `tap_hold_ms` there too, right after
   `LiveConnection(...)` is constructed.
3. **In `send_primitive`'s `TAP` branch**, sleep `tap_hold_ms / 1000` seconds between the down and
   the up. Don't multiply by `time_scale`: that setting stretches *scripted waits* for a slower
   device, while this is about the game seeing one frame, which doesn't depend on script pacing.
   Setting it to 0 gives back the old behavior.
4. **Dry run.** `dry_run.DryRunConnection` logs what would be sent. Make its `TAP` log line mention
   the hold (for example `TAP pointer=1 (2536, 914) hold=50ms`) so a dry run reflects real pacing.
5. **Show it in the IDE**, only if it's a small change: a spin box next to the existing time-scale
   control. If that turns out to be more than about 30 minutes of GUI work, leave it out and note it
   in the PR as a follow-up.

## Tests

- `test_connection.py`: patch `_send_control` so it records `time.monotonic()` with each message.
  With `tap_hold_ms = 50`, a `TAP` produces down then up with at least 45 ms between them. With
  `tap_hold_ms = 0`, both are sent with no deliberate gap (under 10 ms).
- `test_model.py` / `test_io.py`: `tap_hold_ms` round-trips through save and load, and a project file
  without it loads as 50.

## Done when

- The tests pass locally and in CI.
- The `mario_platformer` example project loads, and its taps now take 50 ms. Check with a dry run.
- The PR notes that Game Runs with many taps now take slightly longer (50 ms per tap), in case anyone
  relies on exact total run time.
