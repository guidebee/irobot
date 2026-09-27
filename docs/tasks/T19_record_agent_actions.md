# T19 — Record agent actions, thread-safely, with frame numbers

Status: open

| | |
|---|---|
| Fixes | [DP12](../gym_data_path_review.md#dp12--agent-actions-arent-recorded-recording-isnt-thread-safe) |
| Priority / size | P1 / M |
| Depends on | T08 |
| Area | C++: `src/agent/agent_manager.*`, `src/ui/input_manager.cpp` |
| Needs a device | No |

## Why

Ctrl+E (or a `START_RECORDING` control message) records control events to `events.json`, which
`tools/agent_client.py play` can replay. The README says every event, human or agent, is recorded,
but only human input is:

- Human input goes through `AgentManager::PushDeviceControlMessage` (`agent_manager.cpp:411-419`),
  which writes to the file.
- Agent input goes through `ProcessAgentControlMessage`, which calls `controller->PushMessage`
  directly (`agent_manager.cpp:139`) and skips the file.

Also, `fp_events` is opened, written and closed from two threads with no lock: the UI thread (Ctrl+E,
human input) and the agent reader threads (`START/END_RECORDING`). And a recorded event says nothing
about which frame the actor was looking at, which imitation learning needs.

## Steps

1. **One path for both.** Add a source parameter:

   ```cpp
   enum class EventSource { Human, Agent };
   bool PushDeviceControlMessage(const message::ControlMessage* msg,
                                 EventSource source = EventSource::Human);
   ```

   The default keeps every call in `src/ui/input_manager.cpp` and `irobot_core.cpp` compiling
   unchanged. In `ProcessAgentControlMessage`'s `default:` branch, call
   `agent_manager->PushDeviceControlMessage(msg, EventSource::Agent)` instead of
   `controller->PushMessage(msg)`. Keep the warning when the push fails.
2. **Lock the file.** Add a public `SDL_mutex* recording_mutex = nullptr;` to `AgentManager`, create
   it in `Init` and destroy it in `Destroy`. Take it around every use of `fp_events` in
   `StartRecordEvents`, `StopRecordEvents` and `PushDeviceControlMessage`. Starting while already
   recording, or stopping while not, should be a logged no-op, not a second open or a close of null.
3. **Know the current frame.** Add a public `std::atomic<uint64_t> last_sent_frame_number{0};` to
   `AgentManager`. Set it in `SendOpenCVImage` to the frame number T08 put in `msg.id`. It's what
   an agent most recently could have seen. An atomic avoids taking the video lock on the agent
   thread.
4. **Richer records.** When writing an event, parse `JsonSerialize()`'s output into
   `nlohmann::json`, add `"source": "human"` or `"agent"` and `"frame_number": <last_sent_frame_number>`,
   and write the dump. `agent_client.py play` ignores unknown keys when replaying, and so does
   `JsonDeserialize` on the receiving end; the tests below confirm it.
5. **Make the file name configurable** for tests: a public `std::string event_file_name =
   EVENT_FILE_NAME;` member used by `StartRecordEvents`.

## Tests

`tests/test_agent_recording.cpp` (tag `[agent][recording]`). Build an `AgentManager` with a
`Controller` that is `Init`-ed but **not** started (messages just sit in its queue; see
`src/core/controller.cpp`), and set `event_file_name` to a file in a temporary directory.

1. Start recording through `ProcessAgentControlMessage` with a `START_RECORDING` message. Push one
   agent touch through `ProcessAgentControlMessage` and one human touch through
   `PushDeviceControlMessage`. Stop. The file parses as a JSON array. Ignoring the closing
   sentinel entry, there are two events, one with `"source": "agent"` and one with `"human"`, both
   with a `frame_number`.
2. `JsonDeserialize` of a recorded agent event (with the extra keys) still gives a valid touch
   message.
3. Concurrency: one thread starts and stops recording 200 times while another pushes 2,000 agent
   touches. No crash. Run it once with ThreadSanitizer
   (`-DCMAKE_CXX_FLAGS=-fsanitize=thread` in a separate build directory) and report the result in
   the PR.

## Done when

- The tests pass locally and in CI.
- A recording made while `typesafe_agent play --policy heuristic` drives a device replays with
  `agent_client.py play` and reproduces the agent's inputs. This check needs a device and is
  recommended, not required.
- The README sentence about recording is now true. Leave the wording as is, but mention in the PR
  that this task made it true.
