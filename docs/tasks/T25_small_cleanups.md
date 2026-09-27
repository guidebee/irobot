# T25 — `SaveFrame` colours, by-value parameters, Windows port binding

Status: open

| | |
|---|---|
| Fixes | [DP16, DP20](../gym_data_path_review.md#low-severity) |
| Priority / size | P2 / S |
| Depends on | T06 (which changes `SaveFrame`) |
| Area | C++: `src/ai/brain.*`, `src/video/decoder.cpp`, `src/platform/net.cpp` |
| Needs a device | No |

## Why

Three small correctness issues, none of them urgent:

- **Swapped colours in Ctrl+K captures.** `Decoder::SaveFrame` writes a PPM file, and PPM means RGB
  order, but the buffer holds BGR (the converter's target is `AV_PIX_FMT_BGR24`, even though
  `rgb_frame->format` was labelled `RGB24`). Red and blue come out swapped.
- **Copying `VideoBuffer`.** `ai::SaveFrame` and `ai::ConvertToMat` take `video::VideoBuffer` **by
  value** (`src/ai/brain.hpp`), copying the whole struct. It only works because every member is a
  pointer; the first non-pointer member added would silently be read from a stale copy.
- **Port sharing on Windows.** `net_listen` sets `SO_REUSEADDR` (`src/platform/net.cpp:78`). On
  Windows that lets another process bind the same port and receive connections meant for irobot.
  Windows' equivalent of the POSIX behavior is `SO_EXCLUSIVEADDRUSE`. The ports are loopback-only,
  which limits the exposure.

## Steps

1. **Captures.** After T06, `ai::SaveFrame` converts `rendering_frame` to BGR with a
   `FrameConverter`. Save it with `cv::imwrite("capture<N>.png", mat)`: OpenCV expects BGR, so the
   colours come out right, and PNG is easier to open than PPM. Delete `Decoder::SaveFrame` if nothing
   else uses it. Mention the filename change (`.ppm` → `.png`) in the PR.
2. **References, not copies.** Change remaining `video::VideoBuffer` value parameters in
   `src/ai/brain.*` (and anywhere else; search for `VideoBuffer video_buffer)`) to
   `video::VideoBuffer&`. If T06 already deleted `ConvertToMat`, only `SaveFrame` is left.
3. **Windows binding.** In `net_listen`, under `#ifdef __WINDOWS__`, use `SO_EXCLUSIVEADDRUSE`
   instead of `SO_REUSEADDR`. Keep `SO_REUSEADDR` on other platforms: there it only lets a restarted
   irobot rebind a port still in `TIME_WAIT`, which is what it's for.
4. **Optional, only if it stays small:** host and server versions are both hard-coded "1.0.0"
   (`irobot_server/app/build.gradle` `versionName`, `build_server.sh` `IROBOT_VERSION_NAME`, and the
   host's `IROBOT_SERVER_VERSION`). The server rejects a mismatched client, but only if the versions
   actually differ, so a stale server build passes today. If you can derive all three from one place
   (for example `git describe --tags --always`) in under half a day, do it; otherwise write it up as
   a new task file.

## Tests

- A test that `SaveFrame` on a known red frame writes a PNG whose centre pixel reads back (with
  `cv::imread`) as BGR ≈ (0, 0, 255). Write to a temporary directory.
- The Windows socket change can't be unit-tested on Linux CI. Make sure it compiles in the Windows
  CI job, and note in the PR that you checked the Windows build.

## Done when

- The tests pass locally and in CI, including the Windows build job.
- A manual Ctrl+K capture opens with correct colours.
