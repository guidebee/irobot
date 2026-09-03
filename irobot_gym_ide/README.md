# irobot Gym IDE — action-map editor

Status: **Phase 1 implemented** (action definitions — project management, primitive
touch/key events, actions as ordered combinations of them, a live-frame canvas with a
click-to-add / click-to-test loop) **plus a game-run editor** (a node-graph "Game Run" tab: drag
Action/Delay/Repeat nodes onto a canvas and connect them to script a sequence of actions —
including actions run in parallel — then Run it against the live device; see "Game runs" below).
Reward/score extraction (logcat regex, OCR regions) is **not yet built** — see
[`../docs/irobot_gym_ide_design.md`](../docs/irobot_gym_ide_design.md) §Phase 2 and
[`../docs/opengym_implementation_plan.md`](../docs/opengym_implementation_plan.md) §8 for the
design it will implement.

A desktop tool (PySide6) for defining, per game, the named actions an AI agent can take — a GUI
author for the `ActionMap` schema in
[`../docs/opengym_implementation_plan.md` §7.4](../docs/opengym_implementation_plan.md#74-tier-15--named-virtual-button-actions-config-driven-gamepad).
Connects to the same two agent ports as [`../tools/agent_client.py`](../tools/agent_client.py)
(reusing its wire helpers directly, no duplicated protocol code), shows the live frame, and lets
you click to place touch events, combine them into named actions, and test an action against the
real device before any training code exists. It can also **record real touches made directly on
the phone** (not through the mirror) via `adb shell getevent` and turn them straight into named
actions — see [`../docs/irobot_gym_ide_design.md`](../docs/irobot_gym_ide_design.md) §11. See that
doc generally for the design, and [`requirements.txt`](requirements.txt) /
[`examples/`](examples/) to try it.

It is **not** itself a game or a training tool — it produces `project.yaml` files that
`tools/irobot_gym/env.py` (not yet built, see the implementation plan) will eventually load, and
lets an integrator calibrate and test action definitions against a real, running `irobot` process
before any training code exists.

## Setup and run

```bash
pip install -r requirements.txt   # once per machine: PySide6, PyYAML, numpy
irobot_gym_ide.cmd                # Windows
../irobot_gym_ide.sh              # from within this dir, Git Bash / WSL / Linux / macOS
```

The launchers (`irobot_gym_ide.cmd` / `irobot_gym_ide.sh`) live at the repo root, next to this
package, and resolve their own working directory, so they run from anywhere — same pattern as
`tools/agent_client.cmd`/`.sh`. From the repo root:

```bash
irobot_gym_ide.cmd   # Windows
./irobot_gym_ide.sh  # Git Bash / WSL / Linux / macOS
```

**If you have more than one Python install** (e.g. `py -3` resolves to a different interpreter
than the `python`/`pip` you ran the install command with), install the requirements into
whichever interpreter the launcher actually uses (`.cmd` prefers `py -3` when present, same as
`agent_client.cmd`) — `ModuleNotFoundError: No module named 'PySide6'` at launch means a
mismatch, not a missing install; run `py -3 -m pip install -r requirements.txt` (from this
directory) to fix it.

## Game runs

The **Game Run** tab (next to the mirror/actions tab) is a node-graph editor over the actions
defined in the left panel: drag out **Action**, **Delay**, and **Repeat** nodes, then drag from a
node's output port (right edge) to another node's input port (left edge) to connect them —
loosely Scratch-like, but as a connect-the-dots graph rather than snap-together stacked blocks.

- **Sequence**: connect node A's output to node B's input — B runs after A finishes.
- **Parallel**: connect one node's output to more than one target — all of them start at once.
  A node with more than one *incoming* connection waits for every one of them to finish before it
  starts (a join), so parallel branches can be brought back together.
- **Delay**: waits N frames (same unit as an action's own `wait` event) before continuing.
- **Repeat**: has two output ports, `body` and `after`. Connect `body` to the node that starts
  what should repeat; it runs to completion that many times before `after` fires once. A repeat's
  body can itself contain forks/joins or a nested repeat.
- A node with no incoming connection is a root and starts immediately (more than one root starts
  everything in parallel); a node with no outgoing connection just ends that branch.

Click **Run** to execute the graph against the connected device (same connection as the
Actions tab's Test button) and watch the log at the bottom of the tab; **Stop** halts it after the
node currently in flight finishes. Warnings below the canvas flag graph problems statically (an
Action node pointing at a deleted action, a malformed repeat) — see `model.py`'s `GameRun.validate`
and `run_engine.py`'s module docstring for exactly what is and isn't checked. Saved as part of
`project.yaml`, alongside the actions it references.

## Testing

Pure-Python model tests, no Qt/socket/device required:

```bash
python -m unittest discover -s irobot_gym_ide/tests -t .   # from the repo root
```

## Project layout

```
irobot_gym_ide/
├── app.py               # entry point: python -m irobot_gym_ide.app
├── model.py              # headless data model (EventKind, PrimitiveEvent, Action, GameRun, ...)
├── connection.py          # live connection to a running irobot process's agent ports
├── run_engine.py           # executes a GameRun graph (fork/join/repeat) against a LiveConnection
├── device_recorder.py        # adb shell getevent -> named actions
├── io.py                      # project.yaml load/save
├── _agent_client.py            # bundled copy of tools/agent_client.py's wire helpers
├── gui/                         # PySide6 widgets (canvas, inspector, run_editor, main window)
├── examples/                     # sample project.yaml files
└── tests/                         # pure-Python model tests
```

## Roadmap

See [`../docs/opengym_implementation_plan.md`](../docs/opengym_implementation_plan.md) for the
detailed, phased implementation plan.

The near-term goal for the underlying agent API is a proper **OpenAI Gym / Gymnasium-compatible
environment** (`reset()`, `step(action) -> (observation, reward, terminated, truncated, info)`,
defined action/observation spaces) built on top of the same two sockets this IDE uses, so an RL
agent can train against Android games directly. This IDE's `project.yaml` output is meant to feed
that future environment's `ActionMap`. See the main [README](../README.md#roadmap) for the fuller
picture.
