# T11 — Release a pointer where it was, not at (0, 0)

Status: open

| | |
|---|---|
| Fixes | [DP08](../gym_data_path_review.md#dp08--releases-land-at-0-0) |
| Priority / size | P0 / S |
| Depends on | T02 (so the changed tests run in CI) |
| Area | Python: `irobot_gym_ide/connection.py` and its tests |
| Needs a device | No |

## Why

A `RELEASE` event with no position (the normal case: `left_stop`, `run_stop` and every other
"stop" action) is sent at (0, 0) (`irobot_gym_ide/connection.py:210-211`). The comment there says
the server only reads the pointer id and action. That's not true: `irobot_server`'s `injectTouch`
calls `pointer.setPoint(point)` for every action, including release, so the device moves the finger
to the top-left corner and lifts it there. UI elements that only activate when the finger is lifted
over them won't activate, and a game reading pointer positions during the release sees a touch at
the corner.

## Steps

1. In `LiveConnection` (`irobot_gym_ide/connection.py`), change `_held_pointers` from a `set` of
   pointer ids to a `dict` mapping pointer id → the last `(x, y, send_w, send_h)` actually sent for
   that pointer. Record it on `PRESS` and on `MOVE`, **after** any rescaling (so it's in device
   coordinates).
2. On `RELEASE`:
   - if the event has its own `(x, y)`, use it, as today;
   - otherwise use the stored position **and the stored `send_w, send_h`**. Reusing the stored
     screen size matters: if you rescaled the stored point for a different size, it would no longer
     be the point the finger is actually at.

   Delete the misleading comment.
3. `release_all_held()` builds `RELEASE` events per held pointer. It should now release each pointer
   at its stored position (it will, if step 2 is right).
4. Update every place that reads `_held_pointers` as a set (`in` checks keep working on a dict;
   `.add()` and `.discard()` don't). Search the package: `grep -rn _held_pointers irobot_gym_ide`.
5. The existing test `test_release_with_no_position_is_not_rescaled`
   (`irobot_gym_ide/tests/test_connection.py:56`) **asserts the buggy (0, 0) behavior**. Change it to
   assert the new behavior, and say in the PR that this test encoded DP08. This is correcting a test,
   not loosening one.

## Tests

In `irobot_gym_ide/tests/test_connection.py`, using the same `patch.object(conn, "_send_control")`
pattern the file already uses:

1. `PRESS` at (100, 200), then `RELEASE` with no position → the release message's point is
   (100, 200), and its `screen_size` equals the press's.
2. `PRESS` at (100, 200), `MOVE` to (150, 260), `RELEASE` → released at (150, 260).
3. With a detected resolution different from the reference (see the existing rescale tests): the
   release point equals the **rescaled** press point that was actually sent.
4. `release_all_held()` with two held pointers releases each at its own last position.
5. A `RELEASE` with an explicit position still uses that position.

## Done when

- The tests pass locally and in CI, along with the rest of `irobot_gym_ide/tests`.
- No code path sends a release at (0, 0) unless the pointer was really pressed there.
