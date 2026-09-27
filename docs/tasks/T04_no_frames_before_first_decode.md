# T04 — Don't encode agent frames before the first decoded frame

Status: open

| | |
|---|---|
| Fixes | [DP03](../gym_data_path_review.md#dp03--crash-when-an-agent-connects-before-the-first-frame) |
| Priority / size | P0 / S |
| Depends on | T01 (so the new test runs in CI) |
| Area | C++: `src/agent/agent_manager.cpp`, `src/ai/brain.cpp` |
| Needs a device | No |

## Why

When an agent connects to the video port, `AgentStream::AddSession`
(`src/agent/agent_stream.cpp:62-65`) immediately posts `EVENT_NEW_OPENCV_FRAME` so the new client
gets a frame right away. If no video frame has been decoded yet (irobot just started, or the device
screen is off), `rgb_frame` is 0×0 with a null data pointer. `ai::ConvertToMat` then calls
`cv::resize` on an empty image, OpenCV throws `cv::Exception` (`!ssize.empty()`), nothing catches it,
and irobot terminates.

A Gym launcher that starts irobot and connects straight away can hit this on every run. It's
timing-dependent, which makes it look flaky.

## Steps

1. In `AgentManager::HandleEvent` (`src/agent/agent_manager.cpp`, the
   `EVENT_NEW_OPENCV_FRAME` / `EVENT_NEW_DATA_STREAM_CONNECTION` case), after taking
   `video_buffer->mutex`, return early (still unlocking the mutex) when no frame has been decoded
   yet. The simplest reliable check is:

   ```cpp
   AVFrame* rgb = this->video_buffer->rgb_frame;
   if (rgb == nullptr || rgb->data[0] == nullptr || rgb->width <= 0 || rgb->height <= 0)
   {
       util::mutex_unlock(this->video_buffer->mutex);
       return ui::EVENT_RESULT_CONTINUE;
   }
   ```

   Don't update `last_video_send_ticks` in this path. The first real frame should go out as soon as
   it arrives.

2. Make `ai::ConvertToMat` (`src/ai/brain.cpp`) defensive too: if the frame has no data or a zero
   dimension, return an empty `cv::Mat` instead of calling `cv::resize`. In
   `AgentManager::SendOpenCVImage`, if the returned mat is empty, return without allocating or
   pushing a message. This protects any future caller, not just `HandleEvent`.

3. Check that a client connected before the first frame still receives frames once decoding
   starts. The decoder posts `EVENT_NEW_OPENCV_FRAME` for every new frame (`Decoder::PushFrame`), so
   no extra code should be needed. Confirm this by reading the code, and state it in the PR.

## Tests

Add `tests/test_agent_frames.cpp` (and add it to `TEST_SOURCE` in `tests/CMakeLists.txt`), tagged
`[agent][frames]`:

1. **`ConvertToMat` on an empty buffer returns an empty mat and doesn't throw.** Create a
   `video::VideoBuffer`, call `Init(&fps_counter, false)` (a default-constructed `FpsCounter` is
   enough, since nothing here renders), and call `ai::ConvertToMat(vb, 800, false)`. Use
   `REQUIRE_NOTHROW` and check `.empty()`. Call `vb.Destroy()` at the end.
2. **`HandleEvent` before the first frame doesn't crash and sends nothing.** Follow the setup in
   `tests/test_agent_reconnect.cpp`: start an `AgentStream` on a test port, connect a loopback
   client, then build an `AgentManager` with `video_buffer` pointing at your empty buffer and
   `agent_stream` pointing at your stream. Push an `SDL_Event` of type `EVENT_NEW_OPENCV_FRAME`
   through `HandleEvent`. Assert it returns `EVENT_RESULT_CONTINUE`, and that the client receives no
   bytes within about 200 ms (use a receive timeout on the client socket).

   Use ports different from `test_agent_reconnect.cpp`'s 39181/39182, for example 39191/39192.

## Done when

- Both tests pass locally and in CI.
- Before your fix, test 1 fails (it throws). Check this by temporarily reverting step 2, and mention
  that you did in the PR.
- Manual check: start irobot with the device screen off (or before unlocking it), connect
  `tools/agent_client.py stream`, then turn the screen on. irobot doesn't crash, and frames appear
  once the screen is on. Note the result in the PR. This check needs a device but isn't required to
  merge.
