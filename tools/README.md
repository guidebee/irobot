# irobot AI-agent tools

`agent_client.py` is a reference/test client for irobot's **AI agent API** — the pair of
TCP ports `AgentManager` opens (`src/agent/agent_manager.cpp`) so an external program can
watch the mirrored screen and drive the device, independently of the human mirror window.
It exists to (a) exercise that API end-to-end and (b) serve as a starting point for writing
your own agent (Python or otherwise) — see [Protocol reference](#protocol-reference) below
if you're doing the latter.

This is a **test/reference client**, not a production automation framework. It does not yet
implement an OpenAI Gym / Gymnasium `Env` interface — see [Roadmap](#roadmap).

## Setup

```bash
pip install -r requirements.txt
```

Or only what you need: `record`/keyboard capture needs `pynput`; `record`/`stream`/
`interactive` (anything that shows video) needs `opencv-python` and `numpy`.

Launchers (resolve their own working directory, so they work from anywhere):

```
tools\agent_client.cmd   ...   # Windows
tools/agent_client.sh    ...   # Git Bash / WSL / Linux / macOS
```

> **Windows note:** the `.cmd` launcher uses `py -3` rather than plain `py`/`python`. The
> script has a `#!/usr/bin/env python3` shebang, and Windows' `py` launcher inspects it —
> on a machine where the `python3` alias resolves to the Microsoft Store's app-execution
> stub instead of a real interpreter, plain `py script.py` fails while `py -3 script.py`
> (which skips shebang resolution) works. If you invoke the script directly instead of via
> the launcher, use `py -3 agent_client.py ...` for the same reason.

All subcommands accept `--host` (default `127.0.0.1`) and `--port` (default `27183`, i.e.
irobot's own `--port`). The agent ports are derived from it: **control = port+1**,
**video = port+2**.

## Subcommands

### `stream` — watch only

```
agent_client.cmd stream
```

Connects to the video port and shows both frame streams irobot sends the agent: a larger
grayscale view (`opencv_mat`) and a small color thumbnail (`screen_shot`), each paired with
an 8-byte perceptual hash. Prints a line whenever the hash changes, as a cheap way to see
irobot's own frame-change detection at work (see [Perceptual hash](#perceptual-hash-what-its-for)
below). Press `q` in a video window, or Ctrl+C, to quit.

### `interactive` — watch *and* control

```
agent_client.cmd interactive --screen-size 1200x2670
```

Same view as `stream`, but the window doubles as a virtual touchscreen: click/drag sends
real touch events to the device, and typing a printable key sends a keycode tap. **Esc**
sends Android BACK to the device (it does not quit the tool — a real phone's back gesture
isn't a "quit" either). **Ctrl+Q** quits (deliberately not plain `q`, since that's a normal
key you may want to send to the device).

`--screen-size WIDTHxHEIGHT` is **required** — see
[Why --screen-size?](#why---screen-size) below. Get it from irobot's own console output at
startup (`Initial texture: WxH`; also printed as `New texture: WxH` after a rotation).

### `record` — capture a session

```
agent_client.cmd record myrun.json --screen-size 1200x2670
```

Like `interactive`, plus every keyboard and touch event gets timestamped and saved to the
given JSON file as you go (in addition to being forwarded live, so you're actually driving
the device while recording — not recording blind). Ctrl+C stops and saves.

Keyboard capture uses `pynput`'s global hook (works regardless of which window has focus,
and covers named keys like arrows/enter that the video window's own key handling can't), so
in `record` — unlike `interactive` — the video window's key handling is switched off, to
avoid double-sending a keypress through both paths.

### `play` — replay a recording

```
agent_client.cmd play myrun.json
```

Replays a JSON event file with its original relative timing. Accepts **either**:

- this script's own `record` output (`{"t": <ms>, "msg_type": ..., ...}`), or
- irobot's **own native** recording — press **Ctrl+E** inside `irobot.exe` itself to
  start/stop recording (no external client needed at all); it writes `events.json` in
  irobot's working directory, covering touch and keyboard the same way, shaped by
  `ControlMessage::JsonSerialize()` (`{"event_time": "YYYY-MM-DD HH:MM:SS.mmm", "msg_type":
  ..., ...}`).

`play` drops a small set of message types before sending — see the comment above
`cmd_play` in the script for the up-to-date list and why (mostly: `msg_type`-less/`UNKNOWN`
records are pointless to forward now that the server-side parser no longer chokes on them;
`START_RECORDING`/`END_RECORDING` are skipped because replaying them would actually
start/stop *another* recording rather than being a no-op).

## Why `--screen-size`?

The AI-agent video port only ever sends a **downscaled** frame (grayscale, capped at 800px
on the long side) — never the real mirrored resolution. That matters because
`irobot_server`'s `PositionMapper.map()` (`control/PositionMapper.java`) requires a touch
event's `screen_size` to be **exactly equal** (`Size.equals()`, no tolerance, no implicit
scaling) to the resolution it internally negotiated for the real video stream — anything
else is silently dropped (a verbose-only log line, no error surfaced anywhere). So this
script can't infer the right value from the frames it receives; it has to be told, and it
scales your click coordinates from thumbnail-space up to that real resolution before
sending. Get the number from irobot's own console output (`Initial texture: WxH`), or
you'll see the cursor move but the device never react (this was a real bug, found and fixed
by testing `interactive` live against a device).

## Perceptual hash: what it's for

Every frame irobot sends the agent (`AgentManager::SendOpenCVImage` in
`src/agent/agent_manager.cpp`) is paired with an 8-byte DCT-based perceptual hash
(`computePHash`), and `stream`/`play` surface Hamming-distance changes to make this
visible. Best guess at intent (this predates the current maintainer's memory of writing it,
so treat this as informed reverse-engineering, not documented fact): a cheap way for a
downstream agent to detect "nothing changed since last frame" — skipping redundant RL steps
or replay-buffer entries, or detecting a stuck/loading state — without decoding and diffing
full frames.

## Protocol reference

If you're writing your own client (any language), this is the actual wire format, verified
against the current source and against a live device:

**Control channel** (`port+1`) — irobot → external client is currently unused (nothing
populates that direction today); external client → irobot is one raw JSON object per
`send()`/`write()` call. `AgentController::ProcessMessages` (`src/agent/agent_controller.cpp`)
treats each `recv()` as exactly one JSON document — there's no length prefix or delimiter —
so **always send one complete message per socket write**, and expect trouble if you don't
(this is a known fragility in the current server-side framing, not a hard protocol
guarantee).

Message shapes (`ControlMessage::JsonSerialize`/`JsonDeserialize`,
`src/message/control_msg.cpp`):

```jsonc
// key/tap
{"msg_type": "CONTROL_MSG_TYPE_INJECT_KEYCODE",
 "key_code": {"action": 0, "key_code": 66, "meta_state": 0}}   // action: 0=down, 1=up

// touch
{"msg_type": "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT",
 "touch_event": {
   "action": 0,        // 0=down, 1=up, 2=move
   "buttons": 1,        // 1 while pressed, 0 on up (AMOTION_EVENT_BUTTON_PRIMARY)
   "pointer": -1,        // POINTER_ID_MOUSE; any other value = a distinct touch pointer
   "pressure": 1.0,
   "position": {
     "screen_size": {"width": 1200, "height": 2670},   // MUST match the real video size exactly
     "point": {"x": 600, "y": 1335}
   }
 }}
```

Android keycode values are in `src/android/keycodes.hpp`; `agent_client.py`'s
`android_keycode()` covers the common ones (letters, digits, D-pad, back/home/enter/etc).

**Video channel** (`port+2`) — irobot → external client only, binary, `BlobMessage`
(`src/message/blob_msg.cpp`): a 40-byte big-endian header (`type, timestamp, id, count,
total_length`, all `u64`), then `count` buffers of `[length: u64][width: u64][height: u64][pixels: length bytes]`.
`pixels` is **raw, uncompressed** interleaved pixel data (BGR for color, grayscale for
`opencv_mat`) — not JPEG/PNG. `type` is `1` = `screen_shot` (small, color), `2` =
`opencv_mat` (larger, grayscale). Channel count per buffer = `length / (width * height)`.

## Roadmap

The near-term goal for this API is a proper **OpenAI Gym / Gymnasium-compatible
environment** (`reset()`, `step(action) -> (observation, reward, terminated, truncated,
info)`, defined action/observation spaces) built on top of these same two sockets, so an RL
agent can train against Android games directly. `agent_client.py` is the exploratory/manual
layer that came first; a `gymnasium.Env` wrapper is the next step, not yet implemented.
Touch is the primary action space (most Android games don't need a hardware keyboard or
gamepad); see the main [README](../README.md#roadmap) for the fuller picture.
