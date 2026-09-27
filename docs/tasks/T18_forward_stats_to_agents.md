# T18 — Forward injection statistics to subscribed agent clients

Status: open

| | |
|---|---|
| Fixes | [DP06](../gym_data_path_review.md#dp06--injection-results-are-invisible) (host → agents) |
| Priority / size | P0 / M |
| Depends on | T17 |
| Area | C++: `src/message/control_msg.*`, `src/agent/agent_manager.*`, `src/agent/agent_controller.*`; Python: `irobot_gym_ide/connection.py`, `tools/agent_client.py` |
| Needs a device | Yes, for the final check |

## Why

After T17, irobot knows when the device rejects input. An agent (or a Gym env) needs to know too,
so it can mark a step unreliable instead of blaming its policy. The agent control port is
two-directional, and the irobot → agent direction already exists (`AgentController::PushMessage`,
with a writer thread per session) but is never used.

**Why clients must opt in:** no client today reads from the control socket. If irobot started
writing to every client unasked, an old client's receive buffer would slowly fill; after that,
that session's writer thread would block on `send` forever, since control sockets have no send
timeout. So statistics go only to clients that ask for them.

## Wire format

- **Client → irobot, subscribe** (a normal framed control message):
  `{"msg_type": "CONTROL_MSG_TYPE_SUBSCRIBE", "topics": ["input_stats"]}`
- **irobot → client, update** (same 4-byte length + JSON framing as the other direction), sent
  whenever T17's holder gets a new version:
  `{"msg_type": "DEVICE_MSG_INPUT_STATS", "input_stats": { ...the device's JSON object... }}`

## Steps

1. **Parse the subscribe message.** In `src/message/control_msg.hpp`, add
   `CONTROL_MSG_TYPE_SUBSCRIBE = 202` next to `START_RECORDING`/`END_RECORDING` (200/201), with a
   comment that it's handled by irobot and never forwarded to the device. In
   `ControlMessage::JsonDeserialize` (`src/message/control_msg.cpp`, the `msg_type` if/else chain
   around line 257), map the string to it, and store whether `"input_stats"` is in `topics` in a new
   `subscribe` struct in the union. Make sure `Serialize` (to the device) returns 0 for this type, so
   it's never sent there, and that `JsonSerialize` handles it (used for recording).
2. **Per-session flag.** Add `bool wants_input_stats = false;` to `ControlSession`
   (`src/agent/agent_controller.hpp`). The message handler receives a message, not a session, so
   extend `AgentController::ProcessMessage` to set the flag directly when it sees
   `CONTROL_MSG_TYPE_SUBSCRIBE` (it has the session in `ProcessMessages`), and not forward that type
   to `message_handler`.
3. **Push to subscribers only.** Add
   `void AgentController::PushJsonToSubscribers(const std::string& json)`. It builds a frame the same
   way `BuildFrame` does (4-byte length + JSON) and queues it only on sessions with
   `wants_input_stats` set (same locking as `PushMessage`).
4. **Deliver updates.** Something has to notice new versions of T17's `DeviceInputStats` and call
   `PushJsonToSubscribers`. The simplest place is `AgentManager::HandleEvent`, which already runs
   for every frame event: compare the holder's `version` with a `last_sent_stats_version` member
   (public, with a default initializer; see the header's comment about aggregates), and push when
   it changed. With no video (a static screen), the encoder's 100 ms repeat still produces frame
   events, so updates aren't starved. If you find they are, use a timer event as T10 does.
5. **Python.** In `irobot_gym_ide/connection.py`:
   - in `connect()`, send the subscribe message;
   - start a second daemon thread that reads framed JSON from `_control_sock` (4-byte big-endian
     length, then JSON) and stores the latest `input_stats` dict under the existing lock;
   - add `def input_stats(self) -> dict | None`;
   - like the video reader, exit quietly when the socket closes.

   In `tools/agent_client.py`, add a `--stats` flag to `stream` that also connects to the control
   port, subscribes, and prints each update.

## Tests

- **C++** (`tests/test_agent_reconnect.cpp` style, tag `[agent][control][stats]`): two control
  clients connect; only one sends the subscribe message. After
  `PushJsonToSubscribers("{\"x\":1}")`, the subscriber receives exactly that framed JSON, and the
  other receives nothing within 200 ms.
- **C++**: `JsonDeserialize` of the subscribe message gives `CONTROL_MSG_TYPE_SUBSCRIBE` with
  `input_stats` set, and `Serialize` returns 0 for it.
- **Python** (`test_connection.py`): with a tiny fake server that writes one framed
  `DEVICE_MSG_INPUT_STATS` message to the control socket after accepting, `input_stats()` returns
  its contents within 1 s. And the first thing the fake server reads from the client is the
  subscribe message.

## Final device check (required)

Repeat T17's wrong-screen-size check, but watch `python tools/agent_client.py stream --stats`
instead of irobot's console. The `touch_size_mismatch` count shown by the client increases. Paste
the output in the PR.

## Done when

- The tests pass locally and in CI.
- The device check passes.
- An old-style client that never subscribes (for example `agent_client.py play`) still works, and
  its session is never sent anything.
