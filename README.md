# iRobot for Android

A C++17 desktop client for mirroring, controlling, and automating Android devices — built as a C++ rewrite
of [scrcpy](https://github.com/Genymobile/scrcpy) with CMake, extended with an **AI agent system** that allows external
programs (including machine learning models) to observe and control Android games and apps in real time.

![irobot_agent](https://github.com/guidebee/irobot/blob/master/docs/irobot_agent.png)

No root access required. Works on GNU/Linux, Windows, and macOS.

---

## Features

- **Screen mirroring** — real-time H.264 video stream rendered via SDL2
- **Audio forwarding** — device audio (Opus/AAC/FLAC/raw) decoded and played back via SDL2, enabled by default
- **Full device control** — keyboard, mouse, touch, scroll, and drag-and-drop
- **Screen recording** — save to MP4 or MKV while mirroring (or headless)
- **Clipboard sync** — bidirectional sync between desktop and device
- **File/APK transfer** — drag and drop files or APKs onto the window
- **Wireless support** — connect over TCP/IP without USB
- **AI agent API** — expose device video and control over sockets so external agents can play games or automate the
  device; see [`tools/agent_client.py`](tools/README.md) for a reference client
- **Image processing** — OpenCV integration for perceptual hashing and frame analysis
- **Android 12+ compatible** — updated server uses the current scrcpy wire protocol

---

## Architecture

### Current Architecture

![irobot_android](https://github.com/guidebee/irobot/blob/master/docs/irobot_android_new_arch.png)

### How it works

```
Android Device                       Desktop (iRobot)
──────────────                       ────────────────
 irobot-server (APK)  ──H.264──►  VideoStream → Decoder → Screen (SDL2)
                      ──Opus/AAC─►  AudioStream → AudioDecoder → AudioPlayer (SDL2)
                      ◄─Control─  Controller  ← InputManager ← SDL Events
                                                     │
                                              AgentManager
                                           ┌──────┴──────┐
                                     AgentStream     AgentController
                                     (video/frames   (receives commands
                                      → AI client)    from AI client)
                                           └──────┬──────┘
                                                   │  TCP (JSON in / binary frames out)
                                          external AI agent
                                     (tools/agent_client.py today;
                                      a Gym/Gymnasium Env is planned
                                      — see Roadmap)
```

The companion `irobot-server` APK is pushed to the device via ADB, captures the screen (and, by default, audio) as an
H.264 + Opus stream, and relays control messages back as Android input events. The **AgentManager** layer bridges device
I/O to external AI clients over TCP sockets, enabling autonomous game playing.

---

## Dependencies

| Library           | Purpose                                         |
|-------------------|-------------------------------------------------|
| **FFmpeg**        | H.264 decode, video recording                   |
| **SDL2**          | Windowing, rendering, event loop                |
| **OpenCV**        | Image processing, perceptual hashing for agents |
| **nlohmann/json** | Control event serialization                     |
| **CMake + vcpkg** | Build system and package management             |
| **ADB**           | Device communication and tunneling              |

---

## Build

### 1. Building the Android Server (`irobot-server`)

The Android server is the APK that runs on the device. It is compiled from Java source under `irobot_server/` using a
Gradle-free script to avoid SSL issues that can occur on some network configurations (e.g. VPN with TLS inspection).

#### Requirements

- Android SDK with **API level 37** and **Build Tools 35.0.0**
- Java JDK 21 (the one bundled with Android Studio works: `<SDK>/openjdk/jdk-21.x.x`)
- MSYS2 / Git Bash on Windows

#### Build steps

```bash
cd /c/workspace/irobot_server

# Set SDK and JDK paths (adjust to your installation)
export ANDROID_HOME="/c/Users/<user>/AppData/Local/Android/Sdk"
export JAVA_HOME="/c/Program Files/Android/openjdk/jdk-21.0.8"
export PATH="$JAVA_HOME/bin:$PATH"

bash build_server.sh
```

Output: `build_manual/irobot-server` (~100 KB DEX jar).

#### Deploy to the desktop client

Copy the built server to both locations so the desktop client can push it to devices:

```bash
cp build_manual/irobot-server /c/workspace/irobot/server/irobot-server
cp build_manual/irobot-server /c/workspace/irobot/build/apps/server/irobot-server
```

#### Known gotchas (already handled by the script)

| Issue                                                     | Fix                                             |
|-----------------------------------------------------------|-------------------------------------------------|
| Platform dir named `android-37.0` instead of `android-37` | Script falls back automatically                 |
| `aidl.exe` rejects POSIX paths on Windows                 | Script converts paths with `cygpath -w`         |
| `d8` not found on Windows                                 | Script uses `d8.bat`                            |
| UTF-8 BOM in Java source files copied from Windows        | Strip with `python3 -c "..."` before building   |
| Missing `android/content/IContentProvider.java`           | Fake stub included in source tree               |
| Socket name mismatch with C++ client                      | `DesktopConnection.java` uses `"irobot"` prefix |

---

### 2. Building the Desktop Client (`irobot`)

#### Requirements

- **CMake** ≥ 3.15
- **Ninja** (recommended; bundled with CLion on Windows)
- **MinGW-w64** GCC ≥ 10 on Windows (bundled with CLion works)
- **vcpkg** with `VCPKG_ROOT` set (for SDL2, nlohmann-json)
- **OpenCV** — on Windows, install via MSYS2:

```bash
pacman -S mingw-w64-x86_64-opencv
```

Add `C:\msys64\mingw64\bin` to `PATH`.

FFmpeg libs for Windows are bundled under `libs/FFmpeg/ffmpeg_x64-windows` — no separate installation needed.

#### Configure and build

```bash
# Configure (first time only)
cmake -B build \
  -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake \
  -G Ninja

# Build
cmake --build build --target irobot
```

With CLion on Windows, open the project and use the IDE build. The CMake cache will pick up the bundled MinGW and Ninja
automatically.

#### Output

```
build/apps/irobot.exe          # desktop client
build/apps/server/irobot-server  # server APK (deployed to device at runtime)
```

---

## Usage

### Basic

```bash
irobot
```

Connects to the first ADB-detected device and opens a mirrored window.

### Capture configuration

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

### Recording

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

### Connection

#### Wireless

1. Connect device to the same Wi-Fi as your computer.
2. Find device IP in Settings → About phone → Status.
3. Enable ADB over TCP/IP: `adb tcpip 5555`
4. Unplug USB, then: `adb connect DEVICE_IP:5555`
5. Run `irobot` normally.

For wireless, reducing quality helps:

```bash
irobot -b2M -m800
```

#### Multiple devices

```bash
irobot --serial 0123456789abcdef
irobot -s 192.168.0.1:5555   # TCP/IP device
```

#### SSH tunnel

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

### Window configuration

```bash
irobot --window-title 'My device'
irobot --window-x 100 --window-y 100 --window-width 800 --window-height 600
irobot --window-borderless
irobot --always-on-top
irobot --fullscreen        # or -f
irobot --rotation 1        # 0=none, 1=90°CCW, 2=180°, 3=90°CW
```

### Other options

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

---

## AI Agent API

Separately from the human mirror window, iRobot always opens two more TCP ports (`AgentManager`,
`src/agent/agent_manager.cpp`) for an external AI/automation client:
**control = `--port`+1** (default 27184) and **video = `--port`+2** (default 27185).

| Socket                             | Direction      | Purpose                                                                                            |
|------------------------------------|----------------|----------------------------------------------------------------------------------------------------|
| **AgentStream** (video port)       | iRobot → Agent | Streams a downscaled grayscale frame + a small color thumbnail, each paired with a perceptual hash |
| **AgentController** (control port) | Agent → iRobot | Receives JSON control messages (touch, keycode, ...) and forwards them to the real device          |

A ready-to-use reference client for this API — live view, click-to-touch control, record/replay — lives in [
`tools/agent_client.py`](tools/README.md); that doc also has the full wire-format reference for writing your own client.

### Message types

- `BLOB_MSG_TYPE_SCREEN_SHOT` — small color thumbnail
- `BLOB_MSG_TYPE_OPENCV_MAT` — larger grayscale frame
- Standard control messages — `INJECT_TOUCH_EVENT`, `INJECT_KEYCODE`, `INJECT_TEXT`, `INJECT_SCROLL_EVENT`, etc. (JSON
  over the control port; see `src/message/control_msg.cpp`)

### Event recording

Press **Ctrl+E** inside `irobot.exe` to start recording every control event (from both human input and any connected
agent) to `events.json` in irobot's working directory, for replay, dataset collection, or imitation learning; Ctrl+E
again stops it. `tools/agent_client.py play`
can replay that file directly.

### Image processing

The `brain` module (`src/ai/brain.cpp`) provides:

- `SaveFrame()` — capture a frame to disk
- `ConvertToMat()` — convert an H.264-decoded `AVFrame` to an OpenCV `Mat` (resized, grayscale)

Every frame sent to an agent is paired with an OpenCV PHash (perceptual hash) for cheap frame-change detection — see [
`tools/README.md`](tools/README.md#perceptual-hash-what-its-for).

---

## Shortcuts

| Action                        | Shortcut                        | macOS             |
|-------------------------------|---------------------------------|-------------------|
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

## Project Structure

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
libs/
└── FFmpeg/             # bundled FFmpeg for Windows x64
irobot_server/
├── app/src/main/java/  # Android server Java source (scrcpy-based)
└── build_server.sh     # Gradle-free build script
tools/
├── agent_client.py     # reference/test client for the AI agent API
└── README.md           # its docs + wire-protocol reference
```

---

## Compatibility

### Server protocol (updated)

The Android server and C++ client have been updated to the current [scrcpy](https://github.com/Genymobile/scrcpy) wire
protocol. Key changes from the original 2020-era protocol:

| Area                   | Change                                                                                                    |
|------------------------|-----------------------------------------------------------------------------------------------------------|
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

This update fixes crashes on Android 12+ (`SurfaceControl.createDisplay` API change) and resolves display corruption
caused by the old header format.

---

## Roadmap

See [`docs/opengym_implementation_plan.md`](docs/opengym_implementation_plan.md) for the detailed, phased
implementation plan for the Gym/Gymnasium `Env` described below (protocol facts verified against source, package
layout, build order).

iRobot's AI agent API was originally built with this goal in mind, and the pieces exist today (video + phash streaming,
touch/keycode injection, event recording) but only as raw sockets plus a manual [reference client](tools/README.md) —
not yet a drop-in RL environment. The next step is an **OpenAI Gym / Gymnasium-compatible `Env`** on top of the same two
ports, so existing RL tooling (Stable-Baselines3, RLlib, CleanRL, ...) can train against Android games with minimal
glue:

- **Action space**: touch first — it's what almost every Android game actually responds to (see the discussion that
  shaped this: mouse and gamepad were deliberately deprioritized, since touch already covers a pointer and most games
  don't need a hardware controller). Keycode injection covers the rest.
- **Observation space**: the existing downscaled grayscale/color frames map naturally onto Gym's typical image `Box`
  space; may want an option for the raw (non-downscaled) frame for agents that need it. Audio is not currently part of
  the observation — worth adding only for genres where sound carries state that isn't visible on screen (rhythm games,
  audio-only cues), not as a default.
- **Reward**: not solved yet, and not solvable generically — Android exposes no standard
  "game score" signal, so this will need per-game logic (score-HUD OCR, template/pixel matching, or similar), supplied
  by whoever wraps a specific game, not by iRobot itself.
- **Episode boundaries** (`reset()`/`terminated`/`truncated`): needs a way to detect game-over/restart screens, likely
  via the same perceptual-hash machinery already in place, plus driving the actual app restart over `adb`.
- **Protocol hardening**: the control channel's current one-JSON-object-per-`recv()`
  framing (see [`tools/README.md`](tools/README.md#protocol-reference)) and the touch channel's exact-match
  `screen_size` requirement are fine for a human-paced test client, but a training loop issuing many steps/second will
  want this made more robust — proper message framing, and the environment tracking/handling resolution changes
  automatically instead of requiring a manually-supplied `--screen-size`.
- **Parallel rollouts**: multiple simultaneous environments means multiple `irobot`
  instances against distinct devices/emulators, each on distinct `--port` values (the agent ports derive from it) — not
  yet automated.

This is exploratory direction, not a committed timeline.

---

## Related Projects

- [scrcpy](https://github.com/Genymobile/scrcpy) — the original C project this is based on
- [AutoAdb](https://github.com/rom1v/autoadb) — auto-start irobot when a device connects (`autoadb irobot -s '{}'`)
