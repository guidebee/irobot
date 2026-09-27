# T16 — Count and log every injection outcome on the device

Status: open

| | |
|---|---|
| Fixes | [DP06](../gym_data_path_review.md#dp06--injection-results-are-invisible) (device side) |
| Priority / size | P0 / M |
| Depends on | T03 |
| Area | Java: `irobot_server/.../control/Controller.java`, `wrappers/InputManager.java`, new `control/InputStats.java` |
| Needs a device | No (a device check is recommended) |

## Why

When an agent's touch has no visible effect, nobody can tell today whether the device threw it away
or the game ignored it. Every rejection path on the device is silent or nearly so:

| Where | What happens today |
|---|---|
| `Controller.handleEvent`, `TYPE_INJECT_TOUCH_EVENT` case (around line 356) | `injectTouch(...)`'s return value is ignored |
| `getEventPointAndDisplayId` (around line 493) | Size mismatch logged only at VERBOSE, which is off by default |
| `injectTouch`, "Too many pointers" | Logged at WARN, but not counted |
| `wrappers/InputManager.injectInputEvent` (line 48) | A plain `false` from the framework isn't logged at all; only exceptions are |

This task makes every outcome countable and visible in the server log. T17 then sends the counts to
the host. It's also step 1 of the plan's WP0.1 investigation (`docs/gym_jev_implementation_plan.md`),
which T22 continues.

## Steps

1. **Create `control/InputStats.java`**, a small thread-safe class of `AtomicLong` counters:

   | Counter | Incremented when |
   |---|---|
   | `touchInjected` | A touch was handed to the framework and it returned `true` |
   | `touchSizeMismatch` | `PositionMapper.map()` rejected the event's `screen_size` |
   | `touchTooManyPointers` | `pointersState.getPointerIndex` returned -1 |
   | `injectReturnedFalse` | `InputManager.injectInputEvent` returned `false` without an exception |
   | `injectFailedPermission` | The `SecurityException` path in `InputManager` |
   | `injectFailedOther` | Any other exception path in `InputManager` |
   | `keyInjected` / `keyRejected` | The same for key events |

   Add a `snapshot()` method returning an immutable copy (a small value class or `long[]`), and a
   `toJson()` returning a compact JSON object with those names in snake_case (T17 sends this string).
   Use plain `StringBuilder` code, no JSON library, since the server has no dependencies.
2. **Make one shared instance** reachable from both `Controller` and `InputManager`. The simplest way
   is a `public static final InputStats INSTANCE` on `InputStats`. Note in a comment that it's
   process-wide on purpose (one server process per device connection).
3. **Count and log at each site** in the table above:
   - size mismatch: WARN, **rate-limited to one line per second**, including both sizes (the text
     the VERBOSE line has today);
   - plain `false` from `injectInputEvent`: WARN, rate-limited, including the event's action and
     display id: `"injectInputEvent returned false (action=%d, display=%d)"`. This is the silent path
     the design doc's §13 couldn't see.

   Write the rate limiter as a tiny reusable class, `util/RateLimitedLog.java`, with the clock
   injectable for tests (for example a `LongSupplier` defaulting to `SystemClock::uptimeMillis`).
4. **Use `injectTouch`'s return value** in `handleEvent` rather than discarding it. If it's `false`
   and none of the specific counters above was incremented, that's a gap in this task: find which
   path it was and count it.

## Tests

`irobot_server/app/src/test/java/com/guidebee/irobot/control/InputStatsTest.java` and
`.../util/RateLimitedLogTest.java` (plain JUnit, no Android classes):

- Counters start at zero; increments show up in `snapshot()`; `toJson()` contains every field with
  the right values, and parses as JSON (check with a simple regex, or `org.json` if it's available
  on the test classpath).
- Rate limiter: with a fake clock, 10 calls within one second log once; a call after 1,001 ms logs
  again.

## Done when

- The tests pass locally and in CI (T03's job).
- `grep -n "injectTouch(" Controller.java` shows no call whose result is ignored.
- Recommended device check: send a touch with a deliberately wrong `screen_size` (for example with
  `tools/agent_client.py interactive --screen-size 100x100`). The server log shows the WARN line
  once per second, not once per event. Paste it in the PR.
