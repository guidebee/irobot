# iRobot — an AI Agent Platform for Android

**iRobot drives real Android devices — phones, tablets, emulators — over ADB, and exposes that control to AI
agents as two plain TCP sockets: one streaming frames out, one taking actions in.** It's a C++23 rewrite of
[scrcpy](https://github.com/Genymobile/scrcpy), and the human mirror window it inherited from scrcpy still works
exactly as before — but the reason this project exists is the **AgentManager** layer built on top of it: a
socket-level API that lets an external program, human tool, or ML model watch a device's screen and act on it in
real time, with no code running on-device beyond the (unmodified-target) app itself. A **Gym IDE** for authoring
and running action graphs against a live device already ships today, alongside a prototype **TypeSafe Jev agent**
(`typesafe_agent/`) that picks actions from a Gym IDE project in a live decision loop. A **Gymnasium-compatible
`Env`** on the same sockets — so scripted runs, RL policies, and Jev can all drive real Android games through one
shared contract — is the near-term roadmap, gated on first fixing the frame and input path it depends on.

No root access required. Works on GNU/Linux, Windows, and macOS.

![irobot_gym_ide](https://github.com/guidebee/irobot/blob/master/docs/irobot_gym_ide.png)

---

## Contents

- [Why iRobot for AI agents](#why-irobot-for-ai-agents)
- [Repository layout](#repository-layout)
- [Architecture](#architecture)
- [The AI Agent API](#the-ai-agent-api)
- [Gym IDE — author and run action graphs against a live device](#gym-ide--author-and-run-action-graphs-against-a-live-device)
- [typesafe-agent — a Jev decision loop (prototype)](#typesafe-agent--a-jev-decision-loop-prototype)
- [Roadmap: a Gym/Gymnasium `Env`](#roadmap-a-gymgymnasium-env)
- [Design documents](#design-documents)
- [Screen mirroring and manual control](#screen-mirroring-and-manual-control)
- [Build](#build)
- [Dependencies](#dependencies)
- [Project structure](#project-structure)
- [Compatibility](#compatibility)
- [Related projects](#related-projects)

---

## Why iRobot for AI agents

- **It's a real device, not a simulator.** The device runs its actual, unmodified app or game; iRobot only
  observes the compressed video stream and injects real Android input events, the same way a scrcpy user's mouse
  and keyboard would. Nothing about the target needs to know an agent is driving it.
- **Video and control are separate, always-on sockets** (`AgentManager`, `src/agent/agent_manager.cpp`),
  independent of the human mirror window — an agent can drive the device with or without anyone watching.
- **Frames arrive pre-processed for cheap decision loops**: a downscaled grayscale frame and a small color
  thumbnail, each paired with an OpenCV perceptual hash, so an agent (or a human tool) can detect "did anything
  change" without touching pixels.
- **Control events can be recorded and replayed** (`Ctrl+E` → `events.json`), a direct path to dataset
  collection or imitation learning. Today this captures human input only; recording agent actions too is
  tracked as [T19](docs/tasks/T19_record_agent_actions.md).
- **A desktop authoring tool (Gym IDE) already exists** for turning raw touches into named, reusable actions and
  wiring them into branching action graphs — see [screenshot below](#gym-ide--author-and-run-action-graphs-against-a-live-device) — so integrators can
  build and test a game's action vocabulary before any training code exists.
- **A Gym/Gymnasium `Env` is the explicit next step** ([roadmap](#roadmap-a-gymgymnasium-env)), designed against a
  point-by-point comparison with [DeepMind's AndroidEnv](https://github.com/google-deepmind/android_env) — the
  closest prior art for this exact problem shape (arbitrary apps/games, a universal touchscreen action interface,
  pixel observations) — and planned in detail, work package by work package, in
  [`docs/gym_jev_implementation_plan.md`](docs/gym_jev_implementation_plan.md).

---

## Repository layout

This is a monorepo: the desktop client and every companion tool it depends on live side by side here, each with
its own README for the details.

| Path                                          | Component                                                                                                           |
|------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`src/`](src/)                                  | `irobot` desktop client (C++23), including the `AgentManager` AI agent API — documented in this README             |
| [`tools/`](tools/README.md)                     | `agent_client.py` — reference/test client and wire-protocol docs for the AI agent API                              |
| [`irobot_gym_ide/`](irobot_gym_ide/README.md)   | Gym IDE (PySide6) — action-map editor and Game Run node-graph editor built on the AI agent API                     |
| [`typesafe_agent/`](typesafe_agent/README.md)   | Prototype decision loop that lets TypeSafe's Jev model pick a Gym IDE project's actions against a live device     |
| [`irobot_server/`](irobot_server/README.md)     | Android server (Java, forked from scrcpy) — built to an APK/DEX and pushed to the device via ADB at connection time |
| [`docs/`](docs/)                                | Architecture diagrams, design docs, implementation plans, and task work orders — see [Design documents](#design-documents) |

`irobot_server` used to be maintained as a separate project; it now lives under
[`irobot_server/`](irobot_server/README.md) with its own build script (`build_server.sh` / `build_server.cmd`),
independent of the CMake build below — see [Building the Android Server](#1-building-the-android-server-irobot-server).

---

## Architecture

![irobot_android](https://github.com/guidebee/irobot/blob/master/docs/irobot_android_new_arch.png)

```
Android Device                       Desktop (iRobot)
──────────────                       ────────────────
 irobot-server (APK)  ──H.264──►  VideoStream → Decoder → Screen (SDL2, human mirror)
                      ──Opus/AAC─►  AudioStream → AudioDecoder → AudioPlayer (SDL2)
                      ◄─Control─  Controller  ← InputManager ← SDL Events (human input)
                                                     │
                                              AgentManager
                                           ┌──────┴──────┐
                                     AgentStream     AgentController
                                     (frame + phash  (JSON control
                                      → AI client)    ← AI client)
                                           └──────┬──────┘
                                                   │  TCP (JSON in / binary frames out)
                                          external AI agent
                                (tools/agent_client.py, Gym IDE, typesafe_agent
                                 today; a Gym/Gymnasium Env is next — see Roadmap)
```

The companion `irobot-server` APK is pushed to the device via ADB, captures the screen (and, by default, audio) as
an H.264 + Opus stream, and relays control messages back as Android input events. The human mirror window and the
**AgentManager** agent sockets are independent consumers of the same device connection — an agent can drive the
device with the window open, minimized, or never opened at all (`--no-display`).

---

## The AI Agent API

Separately from the human mirror window, iRobot always opens two more TCP ports (`AgentManager`,
`src/agent/agent_manager.cpp`) for an external AI/automation client:
**control = `--port`+1** (default 27184) and **video = `--port`+2** (default 27185).

| Socket                             | Direction      | Purpose                                                                                            |
|-------------------------------------|----------------|------------------------------------------------------------------------------------------------------|
| **AgentStream** (video port)       | iRobot → Agent | Streams a downscaled grayscale frame + a small color thumbnail, each paired with a perceptual hash |
| **AgentController** (control port) | Agent → iRobot | Receives length-prefixed JSON control messages (touch, keycode, ...) and forwards them to the real device |

Control messages are framed with a 4-byte big-endian length prefix. The agent video stream is throttled to one
frame per 66 ms (`kMinVideoSendIntervalMs` in `src/agent/agent_manager.cpp`), so observations arrive at about
15 fps at most.

A ready-to-use reference client for this API — live view, click-to-touch control, record/replay — lives in
[`tools/agent_client.py`](tools/README.md); that doc also has the full wire-format reference for writing your own
client in any language.

### Message types

- `BLOB_MSG_TYPE_SCREEN_SHOT` — small color thumbnail
- `BLOB_MSG_TYPE_OPENCV_MAT` — larger grayscale frame
- `BLOB_MSG_TYPE_RESOLUTION` — the undownscaled video stream resolution, sent on connect (no more manually
  reading `--screen-size` off stdout). This is the stream's size, which differs from the physical screen when
  `--max-size` is set, and it isn't re-sent on rotation yet (see [Known data path issues](#known-data-path-issues))
- Standard control messages — `INJECT_TOUCH_EVENT`, `INJECT_KEYCODE`, `INJECT_TEXT`, `INJECT_SCROLL_EVENT`, etc.
  (JSON over the control port; see `src/message/control_msg.cpp`)

### Event recording

Press **Ctrl+E** inside `irobot.exe` to start recording control events to `events.json` in irobot's working
directory, for replay, dataset collection, or imitation learning; Ctrl+E again stops it.
`tools/agent_client.py play` can replay that file directly. Only human input is recorded today: actions sent by
a connected agent are not ([T19](docs/tasks/T19_record_agent_actions.md) adds them).

### Image processing

The `brain` module (`src/ai/brain.cpp`) provides:

- `SaveFrame()` — capture a frame to disk
- `ConvertToMat()` — convert an H.264-decoded `AVFrame` to an OpenCV `Mat` (resized, grayscale)

Every frame sent to an agent is paired with an OpenCV PHash (perceptual hash) for cheap frame-change detection —
see [`tools/README.md`](tools/README.md#perceptual-hash-what-its-for).

### Known data path issues

A code-level [review of the frame and input path](docs/gym_data_path_review.md) (2026-09-27) found 20 issues
(DP01–DP20) that an agent or Gym env would hit. None are fixed yet. The high-severity ones:

| ID   | Issue                                                                                              |
|------|------------------------------------------------------------------------------------------------------|
| DP01 | Agents can receive torn frames (the decoder writes the shared frame without the lock the encoder reads it under) |
| DP02 | Rotation / resolution changes break the agent frame path and are never announced                   |
| DP03 | An agent that connects before the first decoded frame crashes irobot                               |
| DP04 | Frames carry no identity (`id` is always 0) and no usable timestamp                                |
| DP05 | Under backpressure the video queue drops the newest frame and keeps older ones                     |
| DP06 | Nothing tells an agent whether its touch was actually injected on the device                       |
| DP07 | Taps have zero hold time, so games that poll touch state per frame can miss them                   |
| DP08 | Releases are sent at (0, 0) instead of where the finger was                                        |

Related: the Gym IDE design records an open bug where a replay sometimes has no effect on the device, with no
error anywhere ([`irobot_gym_ide_design.md` §13](docs/irobot_gym_ide_design.md)). The fixes are broken into 25
step-by-step work orders (T01–T25) in [`docs/tasks/`](docs/tasks/README.md), with dependencies, build/test
commands, and a definition of done.

---

## Gym IDE — author and run action graphs against a live device

[`irobot_gym_ide/`](irobot_gym_ide/README.md) is a desktop tool (PySide6), built on the same agent API, for
turning raw device input into a reusable, testable action vocabulary — no training code required to get started:

1. **Define actions** — click to place touch events on the live mirror, combine them into named actions (a tap, a
   held d-pad direction, a jump-then-move combo), and test each one against a real device.
2. **Script a Game Run** — a node-graph editor (drag Action / Delay / Repeat / Compare / Find Template / Assert
   nodes onto a canvas and connect them, with fork/join) that lets a human design a branching sequence of
   actions — including conditions on what's currently on screen, e.g. "if the game-over banner is showing, tap
   Retry" — then preview it with a dry run, or click **Run** to replay it against a live device and auto-play
   the game, or as a regression run.
3. **Record and classify real gameplay** — capture raw touches straight off the device (`adb shell getevent`),
   or a whole playthrough as a gameplay session, and classify it against HUD regions into named actions
   automatically.
4. **Export an `ActionMap`** — the Tier 1.5 action schema the planned Gym env will load
   (`irobot_gym_ide/gym_export.py`).

The Reward, Observation, and Reset panels are still stubs; the plan to fill them is WP2.3 of the
[Gym + Jev implementation plan](docs/gym_jev_implementation_plan.md). The worked example is
[`irobot_gym_ide/examples/mario_platformer/`](irobot_gym_ide/examples/mario_platformer), calibrated against
Ampere's Run, the Mario-style platformer in `guidebee/super-morse`. Design rationale and a 2026-09-27 peer
review are in [`docs/irobot_gym_ide_design.md`](docs/irobot_gym_ide_design.md).


```bash
pip install -r irobot_gym_ide/requirements.txt   # PySide6, PyYAML, numpy
irobot_gym_ide.cmd     # Windows
./irobot_gym_ide.sh    # Git Bash / WSL / Linux / macOS
```

It is not itself a game or a training tool — it produces `project.yaml` files, which double as the human-facing
front end for the action vocabulary the planned Gym env (`tools/irobot_gym/env.py`, see Roadmap below) will
eventually load. See [`irobot_gym_ide/README.md`](irobot_gym_ide/README.md) for the full node reference, gameplay
session/HUD classification workflow, project layout, and testing instructions.

---

## typesafe-agent — a Jev decision loop (prototype)

[`typesafe_agent/`](typesafe_agent/README.md) connects to a running `irobot`'s agent sockets, loads a Gym IDE
project's actions, and runs a tick-based loop that asks TypeSafe's Jev model which named action to run next. It
reuses the Gym IDE's `LiveConnection` and project loader instead of re-implementing the wire protocol. It grew
out of a comparison with [`typesafe-mario`](https://github.com/guidebee/typesafe-mario), and targets the
`mario_platformer` example.

```bash
pip install -r typesafe_agent/requirements.txt   # PyYAML; typesafe-sdk for the default `typesafe` policy
./typesafe_agent.sh state-demo    irobot_gym_ide/examples/mario_platformer/project.yaml   # list actions, no device
./typesafe_agent.sh latency-check irobot_gym_ide/examples/mario_platformer/project.yaml --action jump
./typesafe_agent.sh play          irobot_gym_ide/examples/mario_platformer/project.yaml --policy heuristic
```

`play` with the default `typesafe` policy needs `TYPESAFE_API_KEY`; `--policy heuristic` needs no key and is the
way to smoke-test the loop. Each decision is logged to `artifacts/run-<timestamp>.jsonl`.

It is a prototype, not a playing strategy: the loop blocks on each decision, and the only observation is a
perceptual-hash "did the screen change" flag, so Jev chooses nearly blind. Phase 4 of the
[Gym + Jev implementation plan](docs/gym_jev_implementation_plan.md) replaces it with an asynchronous Jev policy
over the Gym env, fed structured state from first-party game telemetry.

---

## Roadmap: a Gym/Gymnasium `Env`

The build plan is [`docs/gym_jev_implementation_plan.md`](docs/gym_jev_implementation_plan.md). Its goal is to
let three kinds of "player" drive a real Android game through `irobot` against **one shared contract** for
actions, observations, rewards, and episode boundaries:

| Driver         | What it is                                                         | Exists today?                     |
|-----------------|----------------------------------------------------------------------|-------------------------------------|
| **Scripted**   | A Gym IDE Game Run graph, replayed deterministically               | Yes (`irobot_gym_ide/run_engine.py`) |
| **RL policy**  | A Stable-Baselines3 (or similar) policy trained against a Gymnasium env | No: no env yet                 |
| **Jev policy** | TypeSafe's Jev model choosing actions from structured game state   | Prototype (`typesafe_agent/`)       |

The first target game is Ampere's Run, since the `mario_platformer` example is already calibrated against it and
its source is ours. The plan commits to ten design decisions, among them a **real-time** env (fixed control
rate, actions held between steps, observation age reported), **`Discrete`/`MultiDiscrete`** action encoding so
SB3 can train on it, a fixed canonical observation shape plus optional structured features, one declarative
**`task.yaml`** per game, Jev as an **asynchronous** policy with a decision log, and a **simulator backend** for
games we own. Work is split into phases with milestones:

| Milestone                | Contents                                           | Demonstrates                                           |
|---------------------------|------------------------------------------------------|----------------------------------------------------------|
| **M0** Trustworthy pipe  | Phase 0: silent touch-drop root cause, latency     | Device does what it's told; latency is a known number  |
| **M1** Env on device     | Phases 1–3: `irobot_client/`, `task.yaml`, `IrobotEnv` | `check_env` passes; a random policy runs 1,000 steps  |
| **M2** Jev plays         | Game telemetry, Jev state builders, IDE Agent tab  | Jev with telemetry state plays level 1-1 on device     |
| **M3** Jev authors       | Trace-to-Game-Run compiler, `DECIDE` node          | A Jev playthrough compiled into a replayable Game Run  |
| **M4** Scale             | Simulator, PPO, evaluation harness                 | PPO trained in sim, evaluated on device                |

Phase 0 is a gate: no agent can be evaluated until the device path is trustworthy. Its device-side work is the
[data path task list](docs/tasks/README.md) (T01–T25), which takes precedence over the plan's own step lists
where they overlap.

The earlier [`docs/opengym_implementation_plan.md`](docs/opengym_implementation_plan.md) remains the reference
for design rationale — protocol analysis, package layout, reward tiers, and a design-by-design comparison against
the closest prior art, [DeepMind's AndroidEnv](https://github.com/google-deepmind/android_env) — though its build
order (§12) is superseded and a 2026-09-27 peer review (§15) corrects several of its "current state" statements.
See [`docs/game_run_design_methodology.md`](docs/game_run_design_methodology.md) for the (separate, more
hands-on) methodology its Tier 1.5 action model was first validated against: how to turn a real game's own
source/level data into a verified-safe, hand-authored Game Run today, and what that exercise says still needs to
become reusable tooling on the way to the env.

iRobot's AI agent API was originally built with this goal in mind, and the pieces exist today (video + phash
streaming, touch/keycode injection, event recording, the Gym IDE, the Jev prototype) but only as raw sockets plus
a manual [reference client](tools/README.md) — not yet a drop-in RL environment. The open design problems for
the env, and where the plans stand on them:

- **Action space**: touch first — it's what almost every Android game actually responds to (mouse and gamepad
  were deliberately deprioritized, since touch already covers a pointer and most games don't need a hardware
  controller). Keycode injection covers the rest.
- **Observation space**: a fixed canonical image shape built from the existing downscaled frames (so the shape
  doesn't depend on the device), plus an optional dict of structured features — from first-party game
  telemetry where we own the game, then vision features, then pixels. Audio is not
  currently part of the observation — worth adding only for genres where sound carries state that isn't visible
  on screen, not as a default.
- **Reward**: not solved generically — Android exposes no standard "game score" signal, so this needs per-game
  logic (score-HUD OCR, template/pixel matching, telemetry, or similar), declared per game in its `task.yaml`.
- **Episode boundaries** (`reset()`/`terminated`/`truncated`): needs a way to detect game-over/restart screens,
  likely via the same perceptual-hash machinery already in place, plus driving the actual app restart over `adb`.
- **Protocol hardening**: control messages are now length-prefixed. The rest is the
  [data path review](docs/gym_data_path_review.md)'s findings (see
  [Known data path issues](#known-data-path-issues)) and their [work orders](docs/tasks/README.md).
- **Parallel rollouts**: multiple simultaneous environments means multiple `irobot` instances against distinct
  devices/emulators, each on distinct `--port` values (the agent ports derive from it) — not yet automated.

The plan carries per-work-package estimates, but it is a plan, not a committed timeline. Feasibility notes for latency-sensitive genres
(real-time shooting/fighting games specifically) are in
[the implementation plan §1.1](docs/opengym_implementation_plan.md#11-feasibility-assessment-real-time-shootingfighting-games-specifically).

---

## Design documents

| Document | What it covers |
|---|---|
| [`docs/gym_jev_implementation_plan.md`](docs/gym_jev_implementation_plan.md) | **The current build plan**: Gym env + TypeSafe Jev integration, ten design decisions, phases, work packages, milestones, risks |
| [`docs/gym_data_path_review.md`](docs/gym_data_path_review.md) | Code-level review of the frame and input path (DP01–DP20); read before the plan |
| [`docs/tasks/`](docs/tasks/README.md) | T01–T25: step-by-step work orders that fix the data path findings, with dependencies and a definition of done |
| [`docs/opengym_implementation_plan.md`](docs/opengym_implementation_plan.md) | Original Gym env design: protocol analysis, action/observation tiers, AndroidEnv comparison, 2026-09-27 peer review |
| [`docs/irobot_gym_ide_design.md`](docs/irobot_gym_ide_design.md) | Gym IDE design: data model, reuse of the wire client, known bugs, 2026-09-27 peer review |
| [`docs/game_run_design_methodology.md`](docs/game_run_design_methodology.md) | How to turn a game's own source/level data into a verified, hand-authored Game Run |
| [`irobot_gym_ide/docs/`](irobot_gym_ide/docs/) | Game Run editor guide, action classification design, Game Run AI-assist design |

---

## Screen mirroring and manual control

![irobot_agent](https://github.com/guidebee/irobot/blob/master/docs/irobot_agent.png)

Because iRobot is built on scrcpy, everything below the agent layer also works as a standalone mirroring and
remote-control tool — useful on its own, and for driving a device by hand while building or debugging an agent.

- **Screen mirroring** — real-time H.264 video stream rendered via SDL2
- **Audio forwarding** — device audio (Opus/AAC/FLAC/raw) decoded and played back via SDL2, enabled by default
- **Full device control** — keyboard, mouse, touch, scroll, and drag-and-drop
- **Screen recording** — save to MP4 or MKV while mirroring (or headless)
- **Clipboard sync** — bidirectional sync between desktop and device
- **File/APK transfer** — drag and drop files or APKs onto the window
- **Wireless support** — connect over TCP/IP without USB
- **Android 12+ compatible** — updated server uses the current scrcpy wire protocol

### Usage

#### Basic

```bash
irobot
```

Connects to the first ADB-detected device and opens a mirrored window.

#### Capture configuration

```bash
# Limit resolution (preserves aspect ratio)
irobot --max-size 1024
irobot -m 1024

# Change bitrate
irobot --bit-rate 2M
irobot -b 2M

# Limit frame rate
irobot --max-fps 15

# Crop the screen region
irobot --crop 1224:1440:0:0   # 1224x1440 at offset (0,0)

# Lock video orientation (0=natural, 1=90°CCW, 2=180°, 3=90°CW)
irobot --lock-video-orientation 0
```

#### Recording

```bash
# Mirror and record simultaneously
irobot --record file.mp4
irobot -r file.mkv

# Record only (no display window)
irobot --no-display --record file.mp4
irobot -Nr file.mkv
# Stop with Ctrl+C
```

Frames are timestamped on the device, so packet delay variation does not affect the recorded file.

#### Connection

**Wireless**

1. Connect device to the same Wi-Fi as your computer.
2. Find device IP in Settings → About phone → Status.
3. Enable ADB over TCP/IP: `adb tcpip 5555`
4. Unplug USB, then: `adb connect DEVICE_IP:5555`
5. Run `irobot` normally.

For wireless, reducing quality helps:

```bash
irobot -b2M -m800
```

**Multiple devices**

```bash
irobot --serial 0123456789abcdef
irobot -s 192.168.0.1:5555   # TCP/IP device
```

**SSH tunnel**

```bash
# On local machine:
adb kill-server
ssh -CN -L5037:localhost:5037 -R27183:localhost:27183 your_remote_host
# In another terminal:
irobot
```

To force a forward connection instead:

```bash
adb kill-server
ssh -CN -L5037:localhost:5037 -L27183:localhost:27183 your_remote_host
# In another terminal:
irobot --force-adb-forward
```

#### Window configuration

```bash
irobot --window-title 'My device'
irobot --window-x 100 --window-y 100 --window-width 800 --window-height 600
irobot --window-borderless
irobot --always-on-top
irobot --fullscreen        # or -f
irobot --rotation 1        # 0=none, 1=90°CCW, 2=180°, 3=90°CW
```

#### Other options

```bash
irobot --no-audio             # disable audio forwarding (enabled by default)
irobot --no-control          # read-only mirror, no input
irobot --display 1           # mirror a secondary display
irobot --stay-awake          # prevent device sleep
irobot --turn-screen-off     # turn off device screen while mirroring
irobot --show-touches        # show physical touch indicators
irobot --render-expired-frames  # render all frames (higher latency)
irobot --prefer-text         # inject text events instead of key events
irobot --push-target /sdcard/foo/  # change drag-and-drop target directory
```

### Shortcuts

| Action                        | Shortcut                        | macOS             |
|--------------------------------|-----------------------------------|---------------------|
| Toggle fullscreen             | `Ctrl`+`f`                      | `Cmd`+`f`         |
| Resize to 1:1 (pixel-perfect) | `Ctrl`+`g`                      | `Cmd`+`g`         |
| Remove black borders          | `Ctrl`+`x` / double-click       | `Cmd`+`x`         |
| HOME                          | `Ctrl`+`h` / middle-click       | `Ctrl`+`h`        |
| BACK                          | `Ctrl`+`b` / right-click (hold) | `Cmd`+`b`         |
| APP_SWITCH                    | `Ctrl`+`s`                      | `Cmd`+`s`         |
| MENU                          | `Ctrl`+`m`                      | `Ctrl`+`m`        |
| VOLUME_UP                     | `Ctrl`+`↑`                      | `Cmd`+`↑`         |
| VOLUME_DOWN                   | `Ctrl`+`↓`                      | `Cmd`+`↓`         |
| POWER                         | `Ctrl`+`p`                      | `Cmd`+`p`         |
| Turn screen off               | `Ctrl`+`o`                      | `Cmd`+`o`         |
| Turn screen on                | `Ctrl`+`Shift`+`o`              | `Cmd`+`Shift`+`o` |
| Rotate device screen          | `Ctrl`+`r`                      | `Cmd`+`r`         |
| Expand notifications          | `Ctrl`+`n`                      | `Cmd`+`n`         |
| Expand settings panel         | `Ctrl`+`n` (hold)               | `Cmd`+`n` (hold)  |
| Collapse panels               | `Ctrl`+`Shift`+`n`              | `Cmd`+`Shift`+`n` |
| Copy device clipboard         | `Ctrl`+`c`                      | `Cmd`+`c`         |
| Paste to device               | `Ctrl`+`v`                      | `Cmd`+`v`         |
| Copy & paste to device        | `Ctrl`+`Shift`+`v`              | `Cmd`+`Shift`+`v` |
| Toggle FPS counter            | `Ctrl`+`i`                      | `Cmd`+`i`         |

Right-click sends BACK (press and release). The screen turns on automatically if it is off.

---

## Build

### 1. Building the Android Server (`irobot-server`)

The Android server is the APK that runs on the device. It lives in [`irobot_server/`](irobot_server/README.md) and
is compiled from Java source using a Gradle-free script to avoid SSL issues that can occur on some network
configurations (e.g. VPN with TLS inspection). Full requirements, build steps, and known gotchas are in
[`irobot_server/README.md`](irobot_server/README.md); the short version:

```bash
cd irobot_server

export ANDROID_HOME="/c/Users/<user>/AppData/Local/Android/Sdk"
export JAVA_HOME="/c/Program Files/Android/openjdk/jdk-21.0.8"
export PATH="$JAVA_HOME/bin:$PATH"

bash build_server.sh

# deploy the built server to the desktop client
cp build_manual/irobot-server ../server/irobot-server
cp build_manual/irobot-server ../build/apps/server/irobot-server
```

### 2. Building the Desktop Client (`irobot`)

#### Requirements

- **CMake** ≥ 3.15
- **Ninja** (recommended; bundled with CLion on Windows)
- **MinGW-w64** GCC ≥ 13 on Windows (bundled with CLion works) — required for C++23 support
- **vcpkg** with `VCPKG_ROOT` set (for SDL2, nlohmann-json, FFmpeg)
- **OpenCV** — on Windows, install via MSYS2:

```bash
pacman -S mingw-w64-x86_64-opencv
```

Add `C:\msys64\mingw64\bin` to `PATH`.

On Windows, install FFmpeg through vcpkg (once, into your shared `VCPKG_ROOT`):

```bash
$VCPKG_ROOT/vcpkg install ffmpeg:x64-mingw-dynamic
```

On Linux/macOS, install the FFmpeg dev packages via your system package manager instead
(e.g. `apt install libavcodec-dev libavformat-dev libavutil-dev libavdevice-dev libswscale-dev libavfilter-dev libswresample-dev`).

#### Configure and build

```bash
# Configure (first time only)
cmake -B build \
  -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake \
  -DVCPKG_TARGET_TRIPLET=x64-mingw-dynamic \
  -G Ninja

# Build
cmake --build build --target irobot
```

With CLion on Windows, open the project and use the IDE build. The CMake cache will pick up the bundled MinGW and
Ninja automatically.

#### Output

```
build/apps/irobot.exe            # desktop client
build/apps/server/irobot-server  # server APK (deployed to device at runtime)
```

### 3. Running the tests

```bash
# C++ (Catch2)
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
./build/tests/all_tests

# Python, from the repository root (no device or Qt needed)
python -m unittest discover -s irobot_gym_ide/tests -t .
python -m unittest discover -s typesafe_agent/tests -t .

# Java (on-device server)
cd irobot_server && ./gradlew test
```

CI doesn't run any of these suites yet (`ctest` finds no registered tests, and the Python and Java suites
aren't invoked); tasks [T01](docs/tasks/T01_ctest_registration.md)–[T03](docs/tasks/T03_java_tests_in_ci.md)
fix that. See [`docs/tasks/README.md`](docs/tasks/README.md#build-and-test-commands) for more options.

---

## Dependencies

| Library           | Purpose                                         |
|---------------------|----------------------------------------------------|
| **FFmpeg**        | H.264 decode, video recording                   |
| **SDL2**          | Windowing, rendering, event loop                |
| **OpenCV**        | Image processing, perceptual hashing for agents |
| **nlohmann/json** | Control event serialization                     |
| **CMake + vcpkg** | Build system and package management             |
| **ADB**           | Device communication and tunneling              |

---

## Project structure

```
src/
├── irobot.cpp          # entry point, argument parsing
├── core/               # lifecycle, device server, controller
├── android/            # ADB communication, input event types
├── message/            # control/device/blob message serialization
├── video/              # H.264 stream, FFmpeg decoder, recorder
├── agent/              # AI agent manager, controller, stream
├── ai/                 # image processing (brain.cpp)
├── ui/                 # SDL window, input manager, event converter
├── platform/           # cross-platform net/command (Windows + Unix)
└── util/               # circular buffers, queues, locks, logging
server/
└── irobot-server       # compiled Android APK deployed to device
irobot_server/          # Android server source + build script (see irobot_server/README.md)
├── app/src/main/java/  # Android server Java source (scrcpy-based)
└── build_server.sh     # Gradle-free build script
irobot_gym_ide/         # action-map editor GUI (see irobot_gym_ide/README.md)
irobot_gym_ide.sh       # launcher (Git Bash / WSL / Linux / macOS)
irobot_gym_ide.cmd      # launcher (Windows)
typesafe_agent/         # Jev decision-loop prototype (see typesafe_agent/README.md)
typesafe_agent.sh       # launcher (Git Bash / WSL / Linux / macOS)
typesafe_agent.cmd      # launcher (Windows)
tools/
├── agent_client.py     # reference/test client for the AI agent API
└── README.md           # its docs + wire-protocol reference
tests/                  # C++ Catch2 tests (all_tests)
docs/
├── gym_jev_implementation_plan.md  # current Gym env + Jev build plan
├── gym_data_path_review.md         # frame/input path review (DP01–DP20)
├── tasks/                          # work orders T01–T25
└── ...                             # earlier design docs, diagrams
```

---

## Compatibility

### Server protocol (updated)

The Android server and C++ client have been updated to the current [scrcpy](https://github.com/Genymobile/scrcpy)
wire protocol. Key changes from the original 2020-era protocol:

| Area                   | Change                                                                                                    |
|--------------------------|----------------------------------------------------------------------------------------------------------|
| Server launch          | Arguments are now `key=value` pairs (e.g. `max_size=1024`) instead of positional                          |
| Audio                  | Server defaults to `audio=true` (Opus); client opens a third socket for it — pass `--no-audio` to disable |
| Video socket handshake | Three-part init: 64-byte device name → 4-byte codec ID → 12-byte session header                           |
| Audio socket handshake | No session header (fixed 48kHz stereo) — just a 4-byte codec ID, then straight into the packet loop       |
| Packet headers         | Unified 12-byte header: `pts_flags(8) + size(4)`; bit 63 = session, bit 62 = config, bit 61 = keyframe    |
| INJECT_KEYCODE         | Added `repeat` field (4 bytes); total 14 bytes                                                            |
| INJECT_TOUCH_EVENT     | Added `actionButton` field (4 bytes); total 32 bytes                                                      |
| INJECT_SCROLL_EVENT    | `hscroll`/`vscroll` changed from int32 to signed i16 fixed-point (server scales ×16)                      |
| BACK_OR_SCREEN_ON      | Added `action` field (DOWN/UP); total 2 bytes                                                             |
| GET_CLIPBOARD          | Added `copyKey` field (0=none, 1=copy, 2=cut); total 2 bytes                                              |
| SET_CLIPBOARD          | Added 8-byte sequence and paste flag; length prefix changed 2→4 bytes                                     |
| SET_DISPLAY_POWER      | Renamed from SET_SCREEN_POWER_MODE; payload is now a boolean                                              |
| Device messages        | Clipboard length changed 2→4 bytes; ACK_CLIPBOARD and UHID_OUTPUT types added                             |
| Type numbers           | COLLAPSE_PANELS=7, GET_CLIPBOARD=8, SET_CLIPBOARD=9, SET_DISPLAY_POWER=10, ROTATE_DEVICE=11               |

This update fixes crashes on Android 12+ (`SurfaceControl.createDisplay` API change) and resolves display
corruption caused by the old header format.

---

## Related projects

- [scrcpy](https://github.com/Genymobile/scrcpy) — the original C project this is based on
- [typesafe-mario](https://github.com/guidebee/typesafe-mario) — a TypeSafe/Jev agent that plays NES Super Mario
  Bros from emulator RAM; the model for `typesafe_agent/`
- [AutoAdb](https://github.com/rom1v/autoadb) — auto-start irobot when a device connects (`autoadb irobot -s '{}'`)
- [AndroidEnv](https://github.com/google-deepmind/android_env) — DeepMind's RL platform for Android; closest prior
  art to the planned Gym/Gymnasium `Env` above (same problem shape: arbitrary apps/games, a universal touchscreen
  action interface, pixel observations). Its `Task` protobuf, action-space, and reward/episode-boundary design
  directly shaped this project's plan — see
  [`docs/opengym_implementation_plan.md`](docs/opengym_implementation_plan.md#14-comparison-with-androidenv) for a
  full point-by-point comparison, including where and why this plan deliberately diverges from it.
</content>
