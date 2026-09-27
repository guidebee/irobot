# T08 — Frame numbers and timestamps in video messages

Status: open

| | |
|---|---|
| Fixes | [DP04](../gym_data_path_review.md#dp04--no-frame-identity-or-usable-timestamp) |
| Priority / size | P0 / M |
| Depends on | T06 |
| Area | C++: `src/video/*`, `src/agent/agent_manager.cpp`; Python: `tools/agent_client.py`; docs |
| Needs a device | No |

## Why

Every video message today has `id = 0`, and its `timestamp` is the host's wall-clock time when it
was *encoded* (`src/agent/agent_manager.cpp:250-254`). A client can't tell a new frame from a
repeat, count dropped frames, match a grey `OPENCV_MAT` to the colour `SCREEN_SHOT` made from the
same source frame, or work out how old a frame is. A Gym env needs all four.

The information exists but is thrown away. The decoder counts frames (`frame_number`), and every
video packet carries the device's presentation timestamp (parsed in `src/video/stream.cpp:76`).

## Wire format change (backward compatible)

Two changes to `BLOB_MSG_TYPE_SCREEN_SHOT`, `BLOB_MSG_TYPE_OPENCV_MAT`, and
`BLOB_MSG_TYPE_RESOLUTION`:

1. **`id` in the 40-byte header becomes the source frame number** (starting at 1). It's always 0
   today, so no existing reader depends on it.
2. **One extra buffer is appended at the end** (so `count` goes up by one). It uses the normal buffer
   framing `[length:u64][width:u64][height:u64][payload]`, with `width = height = 0` and a 28-byte
   big-endian payload:

   | Offset | Type | Field | Meaning |
   |---|---|---|---|
   | 0 | u32 | magic | `0x464D4431` ("FMD1"). Identifies this buffer as frame metadata, version 1 |
   | 4 | u64 | frame_number | Same as the header `id` |
   | 12 | i64 | device_pts_us | The device's presentation timestamp in microseconds, or -1 if unknown |
   | 20 | u64 | age_at_send_us | Microseconds from "frame decoded" to "message queued", measured on one monotonic clock inside irobot |

Why this stays compatible: every reader in the repo (`read_blob_message` in `tools/agent_client.py`,
`LiveConnection._read_loop` in `irobot_gym_ide/connection.py`) loops over `count` buffers and uses
only index 0 (image) and index 1 (phash, `SCREEN_SHOT` only). A trailing extra buffer is read and
ignored.

**Why `age_at_send_us` and not an absolute timestamp:** comparing clocks across two processes is
error-prone. A client can compute a frame's age as `(its own time now - its own receive time) +
age_at_send_us`, using only its own monotonic clock. The existing wall-clock `timestamp` header
field stays as it is.

## Steps

1. **Carry per-frame data through the swap.** In `VideoBuffer` (`src/video/video_buffer.hpp`), add a
   small struct with `frame_number`, `device_pts_us` and `decoded_at_us` for each of the decoding and
   rendering frames, and swap them in `SwapFrames()` together with the `AVFrame` pointers.
2. **Fill them in the decoder.** In `Decoder::Push`, after a frame is received and before
   `PushFrame()`:
   - `frame_number`: the existing counter;
   - `device_pts_us`: `decoding_frame->pts`, or -1 if it's `AV_NOPTS_VALUE`;
   - `decoded_at_us`: current monotonic time, `SDL_GetPerformanceCounter() * 1000000 /
     SDL_GetPerformanceFrequency()`. Write a small helper `util::MonotonicMicros()` so it's in one
     place.

   Confirm in the PR that `pts` really is in microseconds for this stream. The server's packet
   header carries microseconds in scrcpy-derived code, but check `irobot_server`'s
   `SurfaceEncoder`/streamer to be sure, and note where you checked.
3. **Write them into messages.** In `SendOpenCVImage` and `SendResolution`, set `msg.id` to the
   rendering frame's number and append the metadata buffer as the last buffer. Write a helper that
   builds this buffer, so both functions share one implementation. Update `msg.count` and
   `msg.total_length`.
4. **Python parser.** In `tools/agent_client.py`, add:

   ```python
   FRAME_METADATA_MAGIC = 0x464D4431

   def parse_frame_metadata(buffers):
       """Returns (frame_number, device_pts_us, age_at_send_us) from the last buffer, or None
       if this message has no metadata buffer (older irobot)."""
   ```

   Make `stream` print the frame number and age alongside the phash output.
5. **Document the format** in `tools/README.md`'s protocol reference (the video channel section),
   including the compatibility argument above.

## Tests

- **C++** (`tests/test_agent_frames.cpp`, tag `[agent][metadata]`): after `HandleEvent` with a
  synthetic frame whose number is 7 and `pts` is 123456, the received `OPENCV_MAT` and
  `SCREEN_SHOT` both have header `id == 7`, and a last buffer with magic `FMD1`, frame 7, pts 123456,
  and `age_at_send_us >= 0`. The `SCREEN_SHOT`'s phash is still at index 1.
- **Python** (new `tools/test_agent_client.py`, or wherever T02 put Python tool tests; ask if
  unsure): `parse_frame_metadata` on hand-built bytes returns the right tuple, and returns `None`
  for a message with no metadata buffer. `read_blob_message` still parses an old-format message
  (without the extra buffer) correctly.
- **Compatibility check:** run the existing `irobot_gym_ide/tests` suite unchanged. It must still
  pass.

## Done when

- All tests pass locally and in CI.
- `tools/README.md` documents the metadata buffer.
- `agent_client.py stream` against a real or fake irobot shows increasing frame numbers.
