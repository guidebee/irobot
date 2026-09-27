# Gym data path tasks

Step-by-step work orders for fixing the data path an agent or Gym environment depends on: frames
out of irobot, actions into the device, and the feedback between them. Each task fixes one or more
findings from the [data path review](../gym_data_path_review.md) (IDs `DP01`–`DP20`).

These tasks are written for developers who are new to this codebase. Each one says why it matters,
which files to open, what to change in order, which tests to add, and how to know you're done. If a
step doesn't match what you find in the code, stop and ask; the code may have moved since the task
was written (2026-09-27, `master` at `3e4e081`).

## How to work a task

1. **Pick a task whose dependencies are merged** (see the table below).
2. **Branch** from the latest `master`: `task/T05-frame-converter` (task ID plus a short name).
3. **Read the task and the linked finding** in the review before changing anything.
4. **Make the change in small commits.** Mention the task ID in each commit message, for example
   `T05: extract FrameConverter from Decoder`.
5. **Add the tests the task asks for**, run the whole suite for the area you touched, and make
   sure CI is green.
6. **Open a PR** titled `T05: ...`. The description says what changed, which tests you ran, and
   anything you found that the task didn't expect.
7. **Update the task file's Status line** in the same PR (`Status: done in #NN`).

One task, one PR. If a task turns out bigger than its size estimate, say so in the PR or ask to
split it, rather than growing the PR.

## Build and test commands

**C++ (desktop client, `src/`, tests in `tests/`).** Linux dependencies are the same as CI's
(`.github/workflows/build-and-release.yml`, "Install dependencies" step):

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
./build/tests/all_tests                    # all Catch2 tests
./build/tests/all_tests "[agent]"          # only tests tagged [agent]
ctest --test-dir build --output-on-failure # after T01 lands
```

New `.cpp` files must be added to `COMMON_SOURCES` in the top-level `CMakeLists.txt` (line 88),
which both the app and the test executable use. New test files go in `tests/CMakeLists.txt`'s
`TEST_SOURCE` list. For memory bugs, build with AddressSanitizer:
`cmake -B build-asan -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS="-fsanitize=address -fno-omit-frame-pointer"`.

**Python (`tools/`, `irobot_gym_ide/`, `typesafe_agent/`)**, from the repository root:

```bash
python -m unittest discover -s irobot_gym_ide/tests -t .
python -m unittest discover -s typesafe_agent/tests -t .
```

**Java (`irobot_server/`, the on-device server):**

```bash
cd irobot_server && ./gradlew test         # unit tests under app/src/test
bash build_server.sh                        # builds the server binary irobot pushes to the device
```

**Device tasks** (marked "Needs a device: yes") need an Android phone or emulator with USB
debugging on, `adb` on your PATH, and irobot built. The main [README](../../README.md) explains how
to run it. Write down the device model, Android version, and connection type (USB or Wi-Fi) in your
PR, since results can differ between devices.

## Definition of done (every task)

- The task's own "Done when" list is satisfied.
- New behavior has automated tests unless the task explains why it can't.
- Existing tests still pass, and CI is green.
- No new compiler warnings in files you touched.
- Any doc that describes the behavior you changed is updated in the same PR.
- The task file's Status line is updated.

## Task list

Priority: **P0** blocks trustworthy agent training, **P1** is important, **P2** is cleanup. Size:
**S** is up to one day, **M** is two to three days.

### Phase 1 — Tests run in CI (do these first)

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T01](T01_ctest_registration.md) | Register the C++ tests with CTest | DP15 | P0 | S | — | No |
| [T02](T02_python_tests_in_ci.md) | Run the Python test suites in CI | DP15 | P0 | S | — | No |
| [T03](T03_java_tests_in_ci.md) | Run the server's Java unit tests in CI | DP15 | P1 | S | — | No |

### Phase 2 — Correct frames

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T04](T04_no_frames_before_first_decode.md) | Don't encode agent frames before the first decoded frame | DP03 | P0 | S | T01 | No |
| [T05](T05_frame_converter.md) | Extract a unit-testable `FrameConverter` | DP01 prep | P0 | M | T01 | No |
| [T06](T06_on_demand_area_conversion.md) | Convert agent frames on demand, under the lock, with area filtering | DP01, DP10 | P0 | M | T05 | No |
| [T07](T07_resolution_changes.md) | Handle resolution changes and announce them | DP02 | P0 | M | T06 | Yes (final check) |

### Phase 3 — Frame metadata and delivery

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T08](T08_frame_identity_and_timestamps.md) | Frame numbers and timestamps in video messages | DP04 | P0 | M | T06 | No |
| [T09](T09_latest_wins_video_queue.md) | Make the video queue keep the newest frames | DP05 | P1 | S | T01 | No |
| [T10](T10_trailing_throttle_and_fps_flag.md) | Trailing-edge frame throttle and `--agent-max-fps` | DP09 | P1 | M | T06 | No |

### Phase 4 — Correct actions

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T11](T11_release_at_last_position.md) | Release a pointer where it was, not at (0, 0) | DP08 | P0 | S | T02 | No |
| [T12](T12_minimum_tap_hold.md) | Give taps a minimum hold time | DP07 | P0 | S | T02 | No |
| [T13](T13_disable_nagle.md) | Disable Nagle's algorithm on control sockets | DP11 | P1 | S | T01, T02 | Yes (measurement) |
| [T14](T14_lift_fingers_on_display_change.md) | Lift held fingers when the display changes | DP19 | P1 | M | T03 | Yes (final check) |

### Phase 5 — Injection feedback

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T15](T15_skippable_device_messages.md) | Let the host skip device messages it doesn't know | DP14 | P0 | S | T01 | No |
| [T16](T16_count_injection_outcomes.md) | Count and log every injection outcome on the device | DP06 | P0 | M | T03 | No |
| [T17](T17_send_injection_stats_to_host.md) | Send injection statistics from the device to irobot | DP06 | P0 | M | T15, T16 | Yes (final check) |
| [T18](T18_forward_stats_to_agents.md) | Forward injection statistics to subscribed agent clients | DP06 | P0 | M | T17 | Yes (final check) |

### Phase 6 — Recording and multiple clients

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T19](T19_record_agent_actions.md) | Record agent actions, thread-safely, with frame numbers | DP12 | P1 | M | T08 | No |
| [T20](T20_multiple_control_clients.md) | Warn about, and optionally prevent, competing control clients | DP13 | P1 | S | T01 | No |

### Phase 7 — Client library and verification

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T21](T21_python_frame_freshness.md) | Python client: frame freshness and reader health | DP18, DP04 | P0 | M | T08 | No |
| [T22](T22_reproduce_no_effect_replay.md) | Re-investigate the "replay has no effect" bug with the new instruments | §13 bug | P0 | M | T11, T12, T18, T21 | Yes |
| [T23](T23_latency_measurement.md) | Measure end-to-end latency properly | — | P1 | M | T08, T10, T13, T21 | Yes |
| [T24](T24_data_path_contract_doc.md) | Write the data-path contract and correct the docs | DP17, DP02, DP12 | P1 | S | Most of the above (see the task) | No |

### Phase 8 — Cleanup

| Task | Title | Fixes | Priority | Size | Depends on | Device |
|---|---|---|---|---|---|---|
| [T25](T25_small_cleanups.md) | `SaveFrame` colours, by-value parameters, Windows port binding | DP16, DP20 | P2 | S | T06 | No |

## Dependency graph

Arrows point from a task to the tasks that need it. T24 (the contract doc) comes after nearly
everything, so it's left out of the graph.

```
T01 ──┬── T04
      ├── T05 ── T06 ──┬── T07
      │                ├── T08 ──┬── T19
      │                │         ├── T21 ──┬── T22
      │                │         │         └── T23
      │                │         └── T23
      │                ├── T10 ── T23
      │                └── T25
      ├── T09
      ├── T15 ── T17 ── T18 ── T22
      ├── T20
      └── T13 ── T23          (T13 also needs T02)
T02 ──┬── T11 ── T22
      ├── T12 ── T22
      └── T13
T03 ──┬── T14
      └── T16 ── T17
```

## Suggested lanes for a team

Up to four developers can work in parallel without stepping on each other:

| Lane | Area | Tasks, in order |
|---|---|---|
| A | C++ video path | T01 → T04 → T05 → T06 → T07 → T08 → T10 → T25 |
| B | Python clients | T02 → T11 → T12 → T21 |
| C | Android server | T03 → T16 → T14 |
| D | C++ transport | T09 → T15 → T20 → T13 → T17 → T18 → T19 |

T22, T23 and T24 come last and need results from every lane.

## When to stop and ask

- The code at the line numbers given doesn't look like the task describes.
- A step would change a wire format in a way the task doesn't mention. Old and new clients must
  keep working together unless the task says otherwise.
- A test you didn't touch starts failing.
- You're about to disable, skip, or loosen a test to make CI pass. Don't; ask instead.
