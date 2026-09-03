# irobot Gym IDE — action-map editor

Status: **Phase 1 implemented** (action definitions only — project management, primitive
touch/key events, actions as ordered combinations of them, a live-frame canvas with a
click-to-add / click-to-test loop). Reward/score extraction (logcat regex, OCR regions) is
**not yet built** — see [`../docs/irobot_gym_ide_design.md`](../docs/irobot_gym_ide_design.md)
§Phase 2 and [`../docs/opengym_implementation_plan.md`](../docs/opengym_implementation_plan.md)
§8 for the design it will implement.

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

## Testing

Pure-Python model tests, no Qt/socket/device required (13 tests):

```bash
python -m unittest discover -s irobot_gym_ide/tests -t .   # from the repo root
```

## Project layout

```
irobot_gym_ide/
├── app.py               # entry point: python -m irobot_gym_ide.app
├── model.py              # headless data model (EventKind, PrimitiveEvent, Action, ...)
├── connection.py          # live connection to a running irobot process's agent ports
├── device_recorder.py      # adb shell getevent -> named actions
├── io.py                    # project.yaml load/save
├── _agent_client.py          # bundled copy of tools/agent_client.py's wire helpers
├── gui/                       # PySide6 widgets (canvas, inspector, main window)
├── examples/                   # sample project.yaml files
└── tests/                       # pure-Python model tests
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
