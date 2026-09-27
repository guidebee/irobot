# T20 — Warn about, and optionally prevent, competing control clients

Status: open

| | |
|---|---|
| Fixes | [DP13](../gym_data_path_review.md#dp13--unarbitrated-control-clients) |
| Priority / size | P1 / S |
| Depends on | T01 |
| Area | C++: `src/agent/agent_controller.*`, `src/core/irobot_core.*` |
| Needs a device | No |

## Why

Every connected control client's input is forwarded to the device. Each client picks its own
pointer ids, and the device keeps one `PointersState` for all of them. So if the IDE is connected
"just to watch" and a Gym env is running, and both happen to use pointer 0 (both default to it),
they overwrite each other's finger on the device. That shows up as phantom drags and releases that
nobody sent, with no error anywhere. Two envs accidentally pointed at one irobot corrupt each other
the same way.

## Steps

1. **Always warn.** In `AgentController::RunAcceptor`, after adding a session, if more than one
   session is now connected, log at WARN:
   `"Control client #%d connected while %d other control client(s) are connected: touches from
   different clients share pointer ids on the device"`.
2. **Optional exclusive mode**, flag `--agent-exclusive-control`. Add it the same way T10 adds
   `--agent-max-fps` (option constant, `long_options` entry, parse case, options field, help text),
   and pass it to `AgentController`.
   - In exclusive mode, **the first connected client that is still connected owns input**. When it
     disconnects, ownership passes to the oldest remaining client.
   - In `AgentController::ProcessMessages`, which has the `session`, drop input messages (touch, key,
     text, scroll) from non-owner sessions, with a rate-limited WARN (one line per second per
     session). Always allow non-input messages (`START/END_RECORDING`, and `SUBSCRIBE` if T18 has
     landed), so a watching IDE can still record and read statistics.
   - Write in the help text *why* the first client wins: an env that connects first shouldn't have
     its control taken by a monitoring tool that connects later.

## Tests

In a new `tests/test_agent_control_arbitration.cpp`, reusing `test_agent_reconnect.cpp`'s helpers
(`Connect`, `SendControlMessage`, a counting handler that also records which message type arrived),
tag `[agent][control][exclusive]`:

1. Exclusive off: two clients each send a touch → the handler sees both.
2. Exclusive on: client A connects, then client B; each sends a touch → the handler sees only A's.
3. Exclusive on: A disconnects; B sends a touch → the handler sees it (ownership passed to B).
4. Exclusive on: B (not the owner) sends `START_RECORDING` → the handler sees it.

## Done when

- The tests pass locally and in CI.
- `irobot --help` documents the flag.
- Connecting the IDE and `typesafe_agent` at the same time produces the WARN line in irobot's
  console. Paste it in the PR.
