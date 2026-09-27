# T22 — Re-investigate the "replay has no effect" bug with the new instruments

Status: open

| | |
|---|---|
| Fixes | The open bug in [`irobot_gym_ide_design.md` §13](../irobot_gym_ide_design.md#13-replay-raw-reliability-chase-2026-09-12-continued-same-day-after-12s-pause) (plan WP0.1) |
| Priority / size | P0 / M (investigation; time-box to 3 days, then report) |
| Depends on | T11, T12, T18, T21 (T07, T14 and T20 help too) |
| Area | Investigation; fixes depend on what you find |
| Needs a device | Yes |

## Why

The design doc records a bug that was never solved: replaying a clean, verified recording
(`irobot_gym_ide/examples/mario_platformer/recordings/level1.session.yaml`) *sometimes* has no
effect on the device, while every stage of irobot logs success. It was impossible to diagnose
because the device never said whether it accepted the input. After the earlier tasks, it does
(T17/T18), and several plausible causes have been fixed or can now be switched on and off:

| Hypothesis | What changed | How to test it now |
|---|---|---|
| Touches rejected for a size mismatch | T07 announces resolution changes; T14 fixes stuck fingers | `touch_size_mismatch` in the input stats |
| The framework refused the injection | T16 logs the silent `false` | `inject_returned_false` in the input stats, plus the server's WARN log |
| Taps too short for the game to notice | T12 adds a hold time | Replay with `tap_hold_ms = 0` versus `50` |
| Releases at (0, 0) confusing the game | T11 | Compare builds before and after T11, if still reproducible |
| Another control client using the same pointers | T20 warns | irobot's console, and `--agent-exclusive-control` |
| Game-side state (paused, dialog, not focused) | — | Frames from T21, with the IDE's canvas open |

## Steps

1. **Reproduce first, on the current `master`.** Replay `level1.session.yaml` (Replay Raw in the
   IDE) 10 times, with `python tools/agent_client.py stream --stats` running in another terminal.
   For each attempt, record: did it have an effect (yes/no/partial), the input stats before and
   after, and anything irobot's console printed. A spreadsheet or a table in the PR is fine.
2. If it **doesn't reproduce** in 10 tries, try what the §13 session had: the Debug build, the
   `--headless` flag, and the IDE plus another client connected. If it still doesn't reproduce,
   stop and report that; it may have been fixed by T07, T11, T12 or T14. Say which build you used.
3. If it **reproduces**, use the stats to split the problem:
   - **Size-mismatch or inject-false counts go up during a failed replay** → the device refused the
     input. Follow plan WP0.1 step 2 (`docs/gym_jev_implementation_plan.md`): compare the target
     display id with the real one at replay time.
   - **Counts show every touch injected, but nothing happened** → the game ignored real input. Test
     `tap_hold_ms` 0 versus 50, check for a second client (T20's warning), and look at the frames for
     a pause screen or dialog.
4. **Clean up** the temporary diagnostic the §13 session left in: `log_level=verbose` in
   `src/core/device_server.cpp` (around line 203). Replace it with nothing; T16's WARN logs cover
   what it was for.
5. **Write up** what you found in the design doc: add a dated subsection at the end of §13 saying
   whether it's resolved, the evidence (your table), and the root cause or remaining hypotheses. If
   a fix is needed and is small, make it in this PR; if not, open a new task file describing it.

## Done when

Either:

- the root cause is identified with evidence, fixed, and 10 consecutive replays have the expected
  effect; or
- after the 3-day time-box, the write-up shows which hypotheses were eliminated, with data, and what
  to try next.

In both cases the §13 write-up is updated and `log_level=verbose` is removed.
