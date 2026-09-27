# T14 — Lift held fingers when the display changes

Status: open

| | |
|---|---|
| Fixes | [DP19](../gym_data_path_review.md#low-severity) |
| Priority / size | P1 / M |
| Depends on | T03 (so the Java tests run in CI) |
| Area | Java: `irobot_server/.../control/Controller.java`, `PointersState.java`; Python: `irobot_gym_ide/connection.py` |
| Needs a device | Yes, for the final check |

## Why

Every touch carries the `screen_size` the client believes the video has. `PositionMapper.map()`
drops any event whose size doesn't exactly match the current video size
(`control/PositionMapper.java`), and `injectTouch` returns early **before** updating the server's
`PointersState` (`control/Controller.java`, `getEventPointAndDisplayId`, around line 493).

So if the display changes size (a rotation) while an agent is holding a finger down (for example,
running right), the release it sends afterwards, still sized for the old video, is dropped. Two
things are left wrong:

- **Android** still thinks the finger is down, so the game keeps "running right" forever.
- **The server's `PointersState`** still has the pointer too. The next press with the same pointer
  id reuses it, and Android receives a second down for a finger that never went up, which it may
  reject as an inconsistent event stream.

A release doesn't need an accurate position. The finger is leaving, and the server already knows
where it was.

## Steps

### Part A — releases survive a size mismatch (server)

1. In `injectTouch`, when `getEventPointAndDisplayId` returns `null` **and** the action is
   `MotionEvent.ACTION_UP` **and** `pointersState` already has this pointer id, don't give up:
   - use the pointer's current point (`pointer.getPoint()`, already in device coordinates);
   - use the current `displayData.virtualDisplayId` as the target display;
   - continue exactly as a normal up.

   Log once at INFO: `"Released pointer <id> at its last position after a video size change"`. For
   any other action, keep today's behavior (drop it).
2. You'll need a small way to check "does `pointersState` have this id" without creating it.
   `getPointerIndex` creates a pointer if missing, so add a read-only
   `public boolean contains(long id)` to `PointersState` that uses the existing private `indexOf`.

### Part B — cancel held fingers when the display changes (server)

3. `onNewVirtualDisplay` (`Controller.java:167`) runs on the **capture thread**, but `pointersState`
   is used on the **controller thread** (`handleEvent`). Don't touch `pointersState` from the
   capture thread. Instead:
   - add `private final AtomicBoolean cancelPointersRequested = new AtomicBoolean();`
   - in `onNewVirtualDisplay`, when `old != null` (a real change, not the first display), set it to
     `true`;
   - at the start of each `handleEvent` call, if `cancelPointersRequested.getAndSet(false)` is true,
     call a new `cancelActivePointers()` method.
4. `cancelActivePointers()`: if `pointersState` has any pointers, build one `MotionEvent` with
   `MotionEvent.ACTION_CANCEL` covering all of them (fill `pointerProperties`/`pointerCoords` the
   same way `injectTouch` does, via `pointersState.update(...)`, after marking each pointer up),
   inject it on the current display, then make sure `pointersState` is empty. Add a
   `public void clear()` to `PointersState` for the last part. Log at INFO how many pointers were
   cancelled.

   The cancel only goes out when the next control message arrives. That's acceptable: agents send
   actions continuously, and a finger held by an idle client is harmless until it does.

### Part C — client forgets its held pointers (Python)

5. In `irobot_gym_ide/connection.py`'s `_read_loop`, when a `BLOB_MSG_TYPE_RESOLUTION` arrives with
   a **different** size from the stored one (not the first one), clear the held-pointer bookkeeping
   (the dict from T11, or the set if T11 hasn't landed) and remember that it happened, for example a
   `self.pointers_reset_count` counter, so callers like a Gym env can re-press anything they meant to
   keep holding.

## Tests

- **Java** (`irobot_server/app/src/test/java/.../control/PointersStateTest.java`, new): `contains`
  is false for an unknown id and doesn't create it; true after `getPointerIndex`; `clear()` empties
  the state. `MotionEvent` can't be constructed in plain JVM unit tests, so parts A and B's
  injection is covered by the device check below.
- **Python** (`test_connection.py`): feed `_read_loop` (or the method it calls to handle a
  resolution message) a resolution of 1200×2670, then 2670×1200. Held pointers are cleared after the
  second, and `pointers_reset_count == 1`. A repeat of the same size clears nothing.

## Final device check (required)

1. In the IDE, run a `right_start` (hold) action on a landscape game.
2. Rotate the device, or trigger something that changes the video size (for example, switch to a
   portrait app).
3. Return to the game. The character is **not** still running right.
4. Run `right_start`, then `right_stop`. Both work normally.

Before this task, step 3 shows the character still running, or step 4's press is ignored. Say
which you saw, if you tried it before the change.

## Done when

- The tests pass locally and in CI.
- The device check passes and is written up in the PR.
