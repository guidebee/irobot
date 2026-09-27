# T21 — Python client: frame freshness and reader health

Status: open

| | |
|---|---|
| Fixes | [DP18](../gym_data_path_review.md#low-severity), and the client side of [DP04](../gym_data_path_review.md#dp04--no-frame-identity-or-usable-timestamp) |
| Priority / size | P0 / M |
| Depends on | T08 |
| Area | Python: `irobot_gym_ide/connection.py`, `typesafe_agent/runner.py` and tests |
| Needs a device | No |

## Why

`LiveConnection` is the Python entry point every client uses (the IDE, `typesafe_agent`, and later
the Gym env). Today:

- `latest_frame()` and `latest_thumbnail()` return pixels with no frame id, so a caller can't tell
  whether it's looking at a new frame or the same one as last time. `typesafe_agent`'s runner
  (`runner.py:105`) counts "no new frame arrived" as "the screen didn't change", which isn't the
  same thing.
- `_read_loop` (`connection.py:75-80`) exits silently on any socket error. Callers keep reading the
  last frame forever and never learn the stream died.

T08 puts a frame number and an age in every message. This task makes them usable from Python.

## Steps

1. **A `FrameInfo` dataclass** in `connection.py`:

   ```python
   @dataclass(frozen=True)
   class FrameInfo:
       frame_number: int          # from the metadata buffer; a local counter if irobot is older than T08
       width: int
       height: int
       received_at: float         # time.monotonic() when this client finished reading it
       age_at_send_us: int | None # from metadata; None if unavailable
       device_pts_us: int | None

       def age_ms(self) -> float | None:
           """How old the frame is now: time since receipt plus irobot's own processing time."""
   ```

2. **Record it** in `_read_loop` for each `OPENCV_MAT` and `SCREEN_SHOT`, using
   `agent_client.parse_frame_metadata` (from T08). If a message has no metadata (older irobot),
   increment a local counter so `frame_number` still increases.
3. **New methods:**
   - `latest_frame_info()` and `latest_thumbnail_info()` return the `FrameInfo` for the current
     frame (or `None`).
   - `wait_for_frame(after: int | None, timeout_s: float) -> FrameInfo | None` blocks until a frame
     numbered greater than `after` arrives, or the timeout expires. Use a `threading.Condition` on
     the existing lock, notified by `_read_loop`.
   - `healthy` (property): `False` once the reader thread has exited.
   - `reader_error`: the exception that stopped it, if any. Log it once at WARNING when it happens.
4. **Keep existing methods working unchanged.** `latest_frame()` and `latest_thumbnail()` keep
   their return shapes; the IDE depends on them.
5. **Fix the prototype runner** (`typesafe_agent/runner.py`):
   - Each decision waits for a frame newer than the last one it used, via
     `wait_for_frame(after=last_number, timeout_s=...)`.
   - `stalled_decisions` counts only real "new frame, same picture" cases.
   - Add a separate `frames_missing` count for "no new frame arrived in time", and include it in the
     observation and the log.
   - If `connection.healthy` goes false, stop the run with a clear error rather than looping on a
     dead stream.

## Tests

In `irobot_gym_ide/tests/test_connection.py`, with a small fake video server: a thread that accepts
one connection and writes blob messages you build by hand, including T08's metadata buffer.

1. After the server sends frames 5 and 6, `latest_frame_info().frame_number == 6`.
2. `wait_for_frame(after=6, timeout_s=0.2)` returns `None` when nothing new is sent, and returns
   frame 7 when the server sends it during the wait.
3. A message **without** a metadata buffer still produces increasing frame numbers.
4. When the server closes the socket, `healthy` becomes `False` within 1 s, and `reader_error` is
   set (or `None` for a clean EOF; decide which, and document it).
5. `age_ms()` is roughly `(now - received_at) * 1000 + age_at_send_us / 1000`.

In `typesafe_agent/tests`, one test that the runner stops with an error when the connection reports
unhealthy (use a fake connection object, the same way the existing tests use fakes).

## Done when

- The tests pass locally and in CI.
- The IDE still works: connect, see frames, Test an action. A manual check is enough.
