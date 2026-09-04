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

### Compare Templates and the Compare node

The left panel's **Compare Templates** section captures a reference image from the live frame:
click **Capture Region**, then click-drag a rectangle over the mirror (game-over banner, a
health bar, a specific button's icon — whatever the game run needs to react to), release, and
name it. The captured region is stored in the project's reference resolution (so it's still found
at the right spot even if the live mirror's own pixel size changes between runs) alongside its own
captured pixels; a **Match threshold** (0–1 similarity) controls how close a live comparison has to
be to count as a match, adjustable per template with the template selected.

A **Compare** node in the Game Run tab tests one of these templates against the live frame at that
point in the graph: pick a template in its property combo, then connect its **match** output port
to whatever should run when the region currently looks like the template, and its **no_match**
port to whatever should run otherwise — an if/else condition wired into the run graph, e.g. "if the
game-over banner is showing, tap Retry; otherwise keep playing." See `model.py`'s `ImageTemplate`
and `RunNodeKind.COMPARE`, and `run_engine.py`'s `_run_compare` for exactly how the comparison
works (nearest-neighbor-resized mean absolute grayscale difference — approximate, not
pixel-perfect, by design).

## Gameplay sessions

The left panel's **Gameplay Sessions** section records a whole playthrough as one
**raw, chronological event stream** -- unlike "Record from Device" above, it does not collapse the
recording into a single named `Action`. Click **Record Gameplay Session** (same `adb shell getevent`
capture as "Record from Device", so it needs the project saved first and the device reachable over
adb), play through the game for as long as you like, click **Stop Recording Session**, and name it.
The session is saved to `recordings/<name>.session.yaml`, next to `project.yaml` (see `model.py`'s
`GameplaySession`/`SessionSegment` and `io.py`'s `save_session`/`load_session`/`list_sessions`) --
kept out of `project.yaml` itself since a raw session's event list can be large and isn't part of
the `ActionMap`-shaped authoring schema `env.py` will load.

A saved session starts **unclassified**: its `segments` list is empty, and **Replay Raw** just
resends every recorded event verbatim (identical to running an `Action` built from them). Each
segment is an index range into the session's `events` plus the `action_name` it represents (see
`GameplaySession.validate`, which checks a segment's range and that its `action_name` exists in the
project, the same "return warnings, never raise" convention `Action.validate`/`GameRun.validate`
use). Once `segments` is non-empty, **Replay Classified** becomes usable: it runs each segment's
named `Action` in order, sleeping between them for the real gap (in frames) recorded between that
segment and the previous one, so pacing still reflects how the session actually played out (see
`session_replay.py`'s `SessionPlayer`). Both replay buttons re-read the selected session from disk
on click, so an externally edited/classified file is picked up with no app restart.

### Classifying a session with HUD Regions

The left panel's **HUD Regions** section (below Image Templates) is the built-in way to fill in
`segments` for a game with fixed on-screen controls (a joystick, a jump button, an attack button):
click **Capture HUD Region**, click-drag a rectangle over the control on the live mirror (same
click-drag-release tool "Capture Region" above uses for templates -- the two capture modes are
mutually exclusive, since the canvas only has one at a time), name it, then select it in the list
and type the **Action name** it represents (an existing project action, or a new name you'll add
later -- `GameplaySession.validate` flags a not-yet-existing one, but non-fatally, same as an
unknown action reference anywhere else in this tool). Unlike an Image Template, a HUD region needs
no captured pixels -- it's a pure spatial rectangle in the project's reference resolution, so
classifying a gesture against it is just "which region contains the point where the gesture
started" (see `model.py`'s `HudRegion` and `hud_classifier.py`). If two regions overlap on purpose
(a broad area behind a small, more specific hotspot), the smaller one wins.

With at least one HUD region defined, select a session in the **Gameplay Sessions** list and click
**Classify Session**: it runs every recorded gesture against your regions, writes the resulting
`segments` back to that session's file (asking first if it already has segments, so a re-classify
doesn't silently clobber earlier work), and logs how many gestures matched. This is a purely
spatial, deterministic classifier -- no ML/AI involved -- well suited to fixed HUD controls but not
to gestures whose target isn't a fixed screen position (e.g. "tap wherever the enemy currently is")
or to two meanings sharing one region (a tap vs. a long-press on the same button); those still need
hand-editing a session's `segments:` list, or a future, smarter classification step. See
`GAME_RUN_AI_ASSIST_DESIGN.md` §3 for the human-review precedent such a step should follow.

Two regions touched at overlapping times (e.g. holding `right_button` while tapping `jump_button`)
normally classify as two separate, overlapping segments -- `GameplaySession.validate` flags the
overlap, and it's real: the raw session genuinely has two concurrent touches. When that
combination is actually meaningful as its own move, define a **HUD Combo** below the HUD Regions
list: **Add Combo**, name it, ctrl/shift-click 2+ regions in the "Regions in combo" list to select
exactly the set that must be touched together, and give it an **Action name** (e.g.
`right_button` + `jump_button` -> `right_jump`). Classify Session then folds every cluster of
concurrent gestures whose exact region set matches a combo into one segment spanning the whole
overlap, naming the combo's action instead of the individual regions' -- including a long hold with
several taps nested inside it (holding right while mashing jump collapses to one `right_jump`
segment covering the whole span, not one per tap). A cluster whose region set doesn't exactly match
any defined combo (a third region also overlapping, or no combo defined at all) still falls back to
classifying each region separately, logged as such, so nothing is silently merged that wasn't
explicitly configured (see `hud_classifier.py`'s `classify_session` and `model.py`'s
`HudRegionCombo`).

## Testing

Pure-Python model tests, no Qt/socket/device required:

```bash
python -m unittest discover -s irobot_gym_ide/tests -t .   # from the repo root
```

## Project layout

```
irobot_gym_ide/
├── app.py               # entry point: python -m irobot_gym_ide.app
├── model.py              # headless data model (EventKind, PrimitiveEvent, Action, GameRun,
│                             GameplaySession, SessionSegment, HudRegion, ...)
├── connection.py          # live connection to a running irobot process's agent ports
├── run_engine.py           # executes a GameRun graph (fork/join/repeat) against a LiveConnection
├── session_replay.py        # replays a GameplaySession (raw events, or its classified segments)
├── hud_classifier.py         # classifies a session's gestures against HudRegions -> SessionSegments
├── device_recorder.py          # adb shell getevent -> named actions / raw gameplay sessions
├── io.py                        # project.yaml + gameplay session (recordings/*.session.yaml) load/save
├── _agent_client.py             # bundled copy of tools/agent_client.py's wire helpers
├── gui/                          # PySide6 widgets (canvas, inspector, run_editor, main window)
├── examples/                      # sample project.yaml files
└── tests/                          # pure-Python model tests
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
