# T06 — Convert agent frames on demand, under the lock, with area filtering

Status: open

| | |
|---|---|
| Fixes | [DP01](../gym_data_path_review.md#dp01--torn-frames), [DP10](../gym_data_path_review.md#dp10--aliased-downscaling-and-wasted-conversion) |
| Priority / size | P0 / M |
| Depends on | T05 |
| Area | C++: `src/video/decoder.*`, `src/video/video_buffer.*`, `src/ai/brain.*`, `src/agent/agent_manager.*` |
| Needs a device | No (a device check is recommended) |

## Why

Today the decoder thread converts **every** decoded frame to a full-resolution BGR image in a shared
buffer (`rgb_frame`), **without** holding `video_buffer->mutex` (`src/video/decoder.cpp:146-154`).
The UI thread then reads that buffer under the mutex and downscales it (`src/ai/brain.cpp`).

Two problems follow:
- An agent can get a half-old, half-new frame (DP01).
- The full-size conversion runs about 60 times a second whether or not anyone needs it, and the
  downscale aliases small objects away (DP10).

The fix is to stop keeping a separate RGB copy at all. The decoder already hands each finished
frame to `VideoBuffer::OfferDecodedFrame`, which swaps it into `video_buffer->rendering_frame` under
the mutex. The decoder never writes `rendering_frame` again until the next swap, which also happens
under the mutex. So converting **from `rendering_frame` while holding the mutex** can never see a
partial frame. Converting only when a frame is actually about to be sent, and directly to the
target size with `FrameConverter` (T05), removes the wasted work and the aliasing in the same step.

## Steps

1. **Add converters to `AgentManager`** (`src/agent/agent_manager.hpp`). `AgentManager` is built
   with designated initializers in `src/core/irobot_core.cpp`, so new members must be **public**
   with default initializers (read the comment on `last_resolution_width` in the header for why):

   ```cpp
   video::FrameConverter mat_converter{};    // OPENCV_MAT: gray, <= 800 px
   video::FrameConverter thumb_converter{};  // SCREEN_SHOT: colour, <= 240 px
   ```

   Two instances, because each keeps a scaler for one output size and format.

2. **Convert from `rendering_frame` in `SendOpenCVImage`.** It's always called with the mutex held
   (see `HandleEvent`). Replace the `ai::ConvertToMat` call with:

   ```cpp
   const AVFrame* src = this->video_buffer->rendering_frame;
   cv::Size size = video::FrameConverter::FitWithin(src->width, src->height, max_size);
   cv::Mat mat = converter.Convert(src, size.width, size.height,
                                   color ? video::ConvertedFormat::Bgr24 : video::ConvertedFormat::Gray8);
   if (mat.empty()) return;   // no frame yet (see T04)
   ```

   Pick `converter` from the message type. Everything after that point (building the blob, the phash
   for `SCREEN_SHOT`) stays the same.

3. **Remove the decoder's conversion.** In `Decoder::Push` (`src/video/decoder.cpp`), delete the
   whole `sws_cv_ctx` block and the `sws_scale` call. Keep `frame_number` updated, but move that
   write inside `VideoBuffer::OfferDecodedFrame`, where the mutex is already held: add an
   `int frame_number` parameter, or set a `decoding_frame_number` field that `SwapFrames()` swaps
   along with the frames. Remove `codec_cv_ctx` too. It's a second opened decoder whose only job was
   to hold two numbers.

4. **Migrate the other `rgb_frame` users** (search the tree for `rgb_frame` to be sure):
   - `AgentManager::SendResolution`: read `rendering_frame->width/height` instead.
   - `ai::SaveFrame` (Ctrl+K capture): convert `rendering_frame` to full-size `Bgr24` with a local
     `FrameConverter` and write that.
   - Then delete `rgb_frame` and `buffer` from `VideoBuffer`, and their allocation and freeing in
     `video_buffer.cpp` and `Decoder::Close`.
   - Delete `ai::ConvertToMat` if nothing uses it any more.

5. **Build with AddressSanitizer** and run the full test suite once (see the
   [README](README.md#build-and-test-commands)).

## Tests

Add to `tests/test_agent_frames.cpp` (created in T04), tagged `[agent][frames]`:

1. **The sent frame comes from `rendering_frame`, at the right size.** Put a synthetic 2670×1200
   YUV420P frame into `video_buffer.rendering_frame` (same helper idea as T05). Connect a loopback
   video client, call `HandleEvent` with `EVENT_NEW_OPENCV_FRAME`, and read two blob messages from
   the socket (you can port `read_blob_message` from `tools/agent_client.py` to C++ in the test).
   Assert the `OPENCV_MAT` is 800×360 with one channel, and the `SCREEN_SHOT` is 240×108 with three
   channels plus an 8-byte phash buffer.
2. **No torn frames.** A writer thread repeatedly writes an all-black frame, then an all-white frame,
   into `decoding_frame` and calls `OfferDecodedFrame` (so the swap happens exactly as it does in
   production). A reader thread repeatedly takes the mutex, converts `rendering_frame` with a
   `FrameConverter`, and asserts every pixel of the result is within ±12 of *either* 16 or 235,
   never a mix. Run it for about 2 seconds. Before this task's change, the equivalent test against
   the old `rgb_frame` path would fail; you don't need to prove that, but say in the PR whether you
   tried.

## Done when

- Both tests pass locally, under AddressSanitizer, and in CI.
- `grep -rn rgb_frame src/` returns nothing.
- `Decoder::Push` no longer calls `sws_scale`.
- Recommended device check: run irobot with `tools/agent_client.py stream` against a real game for a
  minute. Frames look right (colours not swapped, no tearing), and `top` shows lower CPU for irobot
  than before. Note the before and after CPU numbers in the PR.
