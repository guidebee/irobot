# T09 — Make the video queue keep the newest frames

Status: open

| | |
|---|---|
| Fixes | [DP05](../gym_data_path_review.md#dp05--backpressure-keeps-old-frames-and-drops-new-ones) |
| Priority / size | P1 / S |
| Depends on | T01 |
| Area | C++: `src/agent/agent_stream.cpp` |
| Needs a device | No |

## Why

`AgentStream` keeps a 4-slot queue of outgoing video messages (`BlobMessageQueue`,
`src/message/blob_msg.hpp:61`). When it's full, `AgentStream::PushMessage`
(`src/agent/agent_stream.cpp:108-130`) **refuses the new message** and logs "Video queue is full",
while the older queued messages are still sent afterwards. So whenever the connection falls behind,
agents get stale frames and the freshest is lost. For real-time control it should be the other way
round: drop the oldest, keep the newest.

One exception: a `BLOB_MSG_TYPE_RESOLUTION` message must **never** be dropped. A client that misses
it will send touches the device silently ignores (see T07).

## Steps

1. In `AgentStream::PushMessage`, replace the "full → refuse" branch. With `this->mutex` already
   held:
   1. Take every queued message out into a small local array (the queue holds at most 4, so this is
      cheap).
   2. Find the **oldest message that isn't a `RESOLUTION`**. Call `Destroy()` on it (it owns malloc'd
      pixels) and drop it.
   3. Push the remaining messages back **in their original order**, then push the new one.
   4. If every queued message is a `RESOLUTION` (practically impossible, but handle it), refuse the
      new message as today, unless it's a `RESOLUTION` itself, in which case drop the oldest
      `RESOLUTION`, since only the latest size matters.
2. Keep returning `true` when the new message was stored and `false` otherwise. `SendOpenCVImage`
   relies on that to free a message that wasn't stored.
3. Replace the per-frame `LOGW` with a counter (`dropped_frames`) and a log line at most once per
   second: `"Video queue full: dropped %u old frame(s) in the last second"`. A warning per frame
   floods the console exactly when things are already slow.
4. Keep `cond_signal` behavior the same: signal when the queue goes from empty to non-empty.

## Tests

Add `tests/test_agent_stream_queue.cpp` (tag `[agent][stream][queue]`). Create an `AgentStream`,
call `Init` with an invalid or dummy socket and **don't call `Start()`**, so nothing drains the queue
and you can inspect it directly. Build messages with a 16-byte `SDL_malloc`'d buffer so `Destroy()`
has something real to free. Use the `id` field to tell them apart.

1. Push 5 `OPENCV_MAT` messages with ids 1–5. The queue holds ids 2, 3, 4, 5, in that order.
2. Push `RESOLUTION` (id 10), then 4 frames with ids 11–14. The queue holds 10, 12, 13, 14: the
   resolution survived and frame 11 was dropped.
3. Run both cases under AddressSanitizer. No leaks, no double frees.

Clean up by draining the queue and calling `Destroy()` on each message at the end of each test
(`AgentStream::Destroy()` does this too).

## Done when

- The tests pass locally, under AddressSanitizer, and in CI.
- The existing `[agent][stream]` tests in `test_agent_reconnect.cpp` still pass.
- The "Video queue is full" warning no longer appears once per frame in a slow-client scenario. To
  check, run `tools/agent_client.py stream` and pause it with Ctrl+Z for a few seconds, then resume.
