# T13 — Disable Nagle's algorithm on control sockets

Status: open

| | |
|---|---|
| Fixes | [DP11](../gym_data_path_review.md#dp11--nagles-algorithm-is-on-everywhere) |
| Priority / size | P1 / S |
| Depends on | T01, T02 |
| Area | C++: `src/platform/net.*`, `src/core/device_server.cpp`, `src/agent/*`; Python clients |
| Needs a device | Yes, for the before/after measurement |

## Why

TCP's Nagle algorithm holds back a small write until the previous one is acknowledged. A tap is two
small writes (down, then up), and so is almost every action an agent sends. With Nagle on, the
second write can wait for an ACK, and with delayed ACKs that can add tens of milliseconds or more
depending on the OS. No socket in irobot or its Python clients turns Nagle off. Upstream scrcpy
disables it on its control socket for exactly this reason.

This task is **measure, fix, measure again**, so the PR shows whether it mattered on real hardware.

## Steps

1. **Measure before.** On a real device, with the current `master`, run:

   ```bash
   python -m typesafe_agent.cli latency-check irobot_gym_ide/examples/mario_platformer/project.yaml --action jump --samples 50
   ```

   (Or use T23's tool if it has landed.) Keep the output. Use a screen where a tap visibly changes
   something; see the latency-check caveats in `docs/gym_jev_implementation_plan.md` WP0.3.

2. **Add a helper** to `src/platform/net.hpp`/`net.cpp`:

   ```cpp
   bool net_set_tcp_nodelay(socket_t socket, bool enable);
   ```

   Use `setsockopt(socket, IPPROTO_TCP, TCP_NODELAY, ...)`. On POSIX you need
   `#include <netinet/tcp.h>`; on Windows, `TCP_NODELAY` comes from the Winsock headers already
   included for `net.cpp`. Log a warning with `perror` on failure, like `net_set_send_timeout` does.

3. **Apply it:**
   - the **device control socket**, right after it connects in `src/core/device_server.cpp`
     (`net_connect` around line 220). Apply it only to the control socket, not the video one: find
     where the control socket is assigned and add the call there;
   - each accepted **agent control** socket in `AgentController::RunAcceptor`
     (`src/agent/agent_controller.cpp`);
   - each accepted **agent video** socket in `AgentStream::RunAcceptor`, next to the existing
     `net_set_send_timeout` call. It helps the last chunk of each frame go out immediately.

4. **Python clients:** set `sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)` on the
   control socket in `irobot_gym_ide/connection.py` (`connect()`) and in every place
   `tools/agent_client.py` opens a control socket (lines 172, 339, 476).

5. **Measure after**, same command, same device, same screen. Put both result sets in the PR as a
   small table (p50, p95, max). If there's no measurable difference, that's a fine result: say so,
   and keep the change, since it removes a latency source that would matter on other OSes or
   connections.

## Tests

- **C++** (`tests/test_net.cpp` or an existing test file, tag `[net]`): connect a loopback socket
  pair, call `net_set_tcp_nodelay(sock, true)`, and read it back with `getsockopt`. It returns 1.
- **Python** (`irobot_gym_ide/tests/test_connection.py`): start a tiny listening socket on
  127.0.0.1 in the test, point `LiveConnection` at it (the video port can be a second listener that
  just accepts), call `connect()`, and assert `getsockopt(IPPROTO_TCP, TCP_NODELAY)` is non-zero on
  `_control_sock`. Then `disconnect()`.

## Done when

- The tests pass locally and in CI.
- The PR contains the before and after latency numbers, the device, and the connection type (USB or
  Wi-Fi).
