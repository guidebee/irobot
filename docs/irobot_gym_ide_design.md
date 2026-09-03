# irobot Gym IDE — Design Doc

Status: **Phase 1 implemented** (action definitions only — project management, primitive
touch/key events, actions as ordered combinations of them, a live-frame canvas with a
click-to-add / click-to-test loop). Reward/score extraction (logcat regex, OCR regions) is
**not yet built** — see [Phase 2](#phase-2-not-yet-built--reward--score-extraction) and
[docs/opengym_implementation_plan.md §8](opengym_implementation_plan.md) for the design it will
implement.

Code: `tools/irobot_gym_ide/`. Tests: `tools/irobot_gym_ide/tests/` (13 tests, pure Python, no
device/Qt required — see [Testing](#testing)).

## 1. What this is

A desktop tool for defining, per Android game, the vocabulary of actions an AI agent can take —
the human-facing front end for the `ActionMap` schema designed in
[opengym_implementation_plan.md §7.4](opengym_implementation_plan.md#74-tier-15--named-virtual-button-actions-config-driven-gamepad).
It is **not** itself a game or a training tool — it produces `project.yaml` files that
`tools/irobot_gym/env.py` (not yet built, see that plan) will eventually load, and lets an
integrator calibrate and test those definitions against a real, running `irobot` process before
any training code exists.

Three things it does *not* try to be, on purpose:

- **Not a game engine.** An earlier discussion considered UPBGE (Blender's game engine) for this;
  rejected — this tool has no scene to render, no physics, no 3D content. What it needs is an
  ordinary desktop GUI toolkit with good "click/drag on an image" support.
- **Not the training pipeline.** It has no notion of reward composition, RL episodes, or agent
  policies. Its job ends at "here is a named, testable action for this game."
  "Which AI agent later plays the game" is entirely out of scope for this tool by design — it
  only needs to produce files another program (the eventual Gym env) can load.
- **Not a re-implementation of the wire protocol.** Every touch/key message this tool sends is
  built by importing `tools/agent_client.py`'s existing `touch_message()` / `keycode_message()` /
  `send_json()` / `read_blob_message()` — see [§4](#4-reuse-not-reimplementation).

## 2. Why PySide6, not UPBGE

The tool's core interaction is "show an image (a device frame), let the user click/drag
points/regions on it, edit their properties in a form, save/load projects." That's a solved
problem in desktop GUI toolkits — `QGraphicsView`/`QGraphicsScene` (Qt) hit-tests, drags, and
z-orders overlay items on a pixmap natively; `QDockWidget` gives the IDE-style panel layout
(project tree, inspector, console) without hand-building one. UPBGE, by contrast, is a 3D game
engine built on Blender's scene/render pipeline — using it here would mean fighting that pipeline
to get an image-with-clickable-overlays widget that Qt provides directly. PySide6 was also chosen
over the lighter Dear PyGui alternative specifically because `QGraphicsView`'s scene graph does
real hit-testing/dragging for free, which the OCR-region phase (dragging a resizable rectangle)
will need as much as the button-region phase (dragging a point) does now.

## 3. Data model (`model.py`)

No Qt import in this file — see [§5](#5-headless-core--gui-is-one-client-of-it). Three types:

```python
class EventKind(str, Enum):
    TAP = "tap"          # DOWN immediately followed by UP -- a quick touch
    PRESS = "press"       # DOWN only; pointer stays held until a matching RELEASE
    RELEASE = "release"   # UP for a pointer a prior PRESS left held
    MOVE = "move"          # MOVE a currently-held pointer to a new (x, y)
    KEY = "key"             # keycode DOWN immediately followed by UP
    WAIT = "wait"            # no wire message -- just a delay (in frames) before the next event

@dataclass
class PrimitiveEvent:
    kind: EventKind
    pointer_id: int = 0
    x: int | None = None
    y: int | None = None
    keycode: int | None = None
    key_name: str | None = None   # resolved via agent_client.android_keycode if keycode is unset
    frames: int = 0                 # WAIT duration; ignored by other kinds

@dataclass
class Action:
    name: str
    events: list[PrimitiveEvent]
    description: str = ""

@dataclass
class Project:
    name: str
    package: str; activity: str; serial: str; host: str; port: int
    reference_width: int; reference_height: int
    actions: dict[str, Action]
```

This is deliberately the minimal vocabulary the user asked for — "start with a simple/single
event, like click on (x, y); actions are combinations of those." A tap action is one `TAP` event.
A "hold left" action is a single `PRESS` event whose pointer is meant to still be held when the
action finishes (the *stop* half is a separate, paired action — see below). A composed gesture
("hold left, and after 10 frames also tap jump") is just a longer event list on one or two
pointers — no special-cased gesture type was needed, matching
[plan §7.1](opengym_implementation_plan.md#71-verified-the-protocol-already-supports-real-concurrent-multi-touch-not-simulated-taps)'s
finding that the wire protocol's real unit is already one message per pointer per event.

This also maps directly onto plan §7.4's `ActionMap`: a `button`'s `region`/`pointer_id` there is
just this tool's `PrimitiveEvent.x/y/pointer_id`, and a `macro` like `long_jump` is exactly the
`PRESS → WAIT(frames) → RELEASE` sequence `examples/mario_platformer.yaml` encodes below. This
tool doesn't introduce a second schema — it's a GUI author for the one the plan already designed.

### 3.1 Validation: two levels, and a false positive worth knowing about

`Action.validate()` checks one action in isolation: unresolvable key events, touch events missing
`(x, y)`, and a **double `PRESS`** on the same pointer with no `RELEASE` between them (the one
thing that's a contradiction regardless of what any other action does).

It deliberately does **not** flag a lone `RELEASE`/`MOVE` with no `PRESS` earlier in the same
action — that's the idiomatic shape of a split start/stop action pair (`move_left_start` PRESSes
pointer 0; `move_left_stop` is a lone RELEASE on pointer 0), a normal, encouraged pattern for
hold-based controls, not a mistake. An earlier version of this check *did* flag it, which is worth
recording as a caught bug: it made every legitimate "stop" action permanently show a validation
error in the inspector, for no real problem — testing the tool against its own worked example
surfaced this immediately (see [§7](#7-known-bugs-found-and-fixed-during-implementation)).

The check that *can* safely span actions is `orphan_releases(actions)` — a project-wide scan: if
some action `RELEASE`s pointer `p` and **no** action anywhere in the project ever `PRESS`es
pointer `p`, that's very likely a typo'd `pointer_id` (there is no "start" action this "stop"
could ever have paired with). This is wired into `main_window.py`'s log panel, alongside
`conflicting_pointer_actions()` (informational: two actions leaving the same pointer held at their
end — expected for `left`/`right` sharing one thumb's pointer, per plan §7.4, but worth surfacing
in case it's actually a missing `RELEASE`).

## 4. Reuse, not reimplementation

`connection.py` imports `tools/agent_client.py` directly (via `_agent_client.py`'s
`importlib`-based loader, so this works whether or not `tools/` is ever turned into a real
package) and calls its existing `touch_message()`, `keycode_message()`, `send_json()`,
`read_blob_message()`, `android_keycode()`, and the `MOTION_ACTION_*`/`ACTION_*`/`BUTTON_PRIMARY`
constants. No wire-format knowledge is duplicated here. This is a deliberate stand-in for the
`protocol.py` extraction plan §5 describes ("refactored OUT of agent_client.py, both import
this") — that extraction hasn't happened yet, so this tool reuses `agent_client.py` as-is rather
than either duplicating its wire code or blocking on a refactor of a file this tool doesn't own.

`LiveConnection` (in `connection.py`) adds exactly two things on top of those primitives:

1. A background thread holding the most recent video frame (the video channel is push-only per
   plan §3.2 — "latest frame" really is the freshest thing on offer, there's nothing to request).
2. Resolving a `model.Action` into real wire messages, tracking which `pointer_id`s are currently
   held **on this connection** so a malformed `RELEASE`/`MOVE`/double-`PRESS` at *runtime* is a
   local no-op with a logged reason rather than a wire error or an exception — the same
   "malformed action → no-op" principle plan §7.1 establishes for the eventual Gym env.
   `release_all_held()` cleans up any pointers left down after testing, mirroring the cleanup the
   plan's §7.1 says a real `reset_episode()` must also do.

## 5. Headless core, GUI is one client of it

`model.py` and `io.py` have zero GUI dependency; `connection.py` has zero GUI dependency (it needs
`numpy`, imported lazily inside `latest_frame()`, mirroring `agent_client.py`'s own lazy-import
pattern so pure protocol-sending code paths don't need it at all). All three are directly usable
from a script or a test with no display server — confirmed by `tests/test_model.py` (13 cases) and
`tests/test_io.py`, which run via plain `unittest` with no Qt import anywhere in the import chain.
This matters because the eventual consumer of a saved project is a *training script*
(`tools/irobot_gym/env.py`), not this IDE — `irobot_gym_ide.io.load_project(path)` needs to work
from a headless CI box exactly as well as from the GUI.

`gui/` (`main_window.py`, `canvas.py`, `inspector.py`) is the one client of that core built so
far. Nothing under `gui/` is imported by `model.py`, `io.py`, or `connection.py`.

## 6. The click-to-test loop

The central interaction, run entirely inside `MainWindow`:

1. **Connect** — `LiveConnection(host, port).connect()`; a `QTimer` (66 ms, ~15 fps) polls
   `latest_frame()` and pushes it into `CanvasView.update_frame()`.
2. **Select an action** in the left dock's list; its events are shown in the right dock
   (`ActionInspector`) and drawn as colored markers on the canvas (`CanvasView.set_markers()`),
   color-coded by `pointer_id`.
3. **Click on the live frame** to append a new event to the selected action at that point.
   Click coordinates arrive in *frame pixel space* (`CanvasView.pointClicked`); `main_window.py`
   converts them to the project's `reference_resolution` before storing them
   (`_frame_to_reference`), and does the inverse (`_reference_to_frame`) when drawing markers —
   the same ratio-scaling `agent_client.py`'s own `interactive`/`record` commands already use, and
   for the same reason (touch coordinates must land in the real device resolution, not whatever
   size the video channel happens to be sending).
4. **Test** sends the whole action live (`LiveConnection.run_action`) and reports any skipped
   (no-op) events in the log panel — so a miscalibrated region or a bad pointer sequence is
   visible in seconds, against the real device, not discovered later inside a training run.
5. **Live send-on-click** (on by default, toggled by a checkbox in the left panel) additionally
   sends *each* newly-added event immediately, one at a time, as you click — see
   [§6.1](#61-live-send-on-click-and-why-test-action-could-look-like-a-no-op) for why this exists
   and the bug that motivated it.

## 6.1 Live send-on-click, and why Test Action could look like a no-op

Reported after first real use: **Test Action appeared to have no effect on the device.** Root
cause, found by tracing the wire message it actually sent: `_test_action()` and `_release_all()`
originally fell back to the *displayed video frame's own dimensions* as `screen_size` whenever
`Reference width/height` hadn't been set — but that frame is always the downscaled
`BLOB_MSG_TYPE_OPENCV_MAT` copy (≤800px long side, plan §6), never the real device resolution.
`irobot_server`'s `PositionMapper.map()` requires `screen_size` to equal the real negotiated
resolution **exactly** (`Size.equals()`, no tolerance — the same fact `agent_client.py`'s own
`--screen-size` requirement exists for, see `tools/README.md#why---screen-size`); any mismatch is
dropped silently, with only a verbose-level server log and no visible error on the client side. So
every test send was protocol-valid JSON that the device was correctly and silently ignoring — "no
effect" was accurate, not a red herring.

Fixed by `_require_reference_resolution()`: `Test Action`, `Release All Held Pointers`, and the new
live-send-on-click path (below) now all refuse to send anything when `Reference width/height`
isn't set, instead logging a specific, loud explanation (naming irobot's own `"Initial texture:
WxH"` startup line as the value to enter) rather than guessing a value that would silently fail.
Verified end-to-end against a throwaway fake TCP server standing in for `irobot`'s control/video
ports: given a real reference resolution, `LiveConnection.send_primitive()` produces exactly the
expected `CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT` DOWN+UP pair with the correct `screen_size`,
`pointer`, and `position`.

Separately, the click-to-add flow now optionally **sends the just-added event live**, per-click,
rather than only in a batch via Test Action — closing the calibration feedback loop discussed when
this tool was scoped ("click, then immediately see whether it landed on the right button"). A
checkbox in the left panel (`Send new events live as you click`, on by default) controls this;
`_on_canvas_clicked()` calls `ActionInspector.add_event_at_point()` (now returns the created
`PrimitiveEvent` instead of `None`) and, if the checkbox is on and a real reference resolution is
set, immediately follows with `LiveConnection.send_primitive()`, logging "sent live" or the no-op
reason for that single event. This is strictly additive to `Test Action`, which still exists for
replaying a whole action's sequence (including timing via `WAIT` events) once it's built up.

## 6.2 Auto-detected reference resolution (Phase 0.2, implemented)

Reported after real use against a live device: even with the §6.1 fixes, an action's Test still
had no effect. Root cause this time: the project's `Reference width/height` simply didn't match
the device's actual resolution — a value the tool had no way to check, since (until now) nothing
on the agent-port wire protocol reported it; the only source of truth was `irobot.exe`'s own
console output (`Initial texture: WxH`), same limitation `agent_client.py`'s `--screen-size` flag
already had. This is exactly the gap `opengym_implementation_plan.md` §4's "Resolution
announcement" Phase 0.2 was designed to close, and it's now implemented (this session, not
originally):

- **C++**: `BLOB_MSG_TYPE_RESOLUTION` (`src/message/blob_msg.hpp`), sent by the new
  `AgentManager::SendResolution()` (`src/agent/agent_manager.cpp`) alongside the existing per-frame
  image sends. Reads `video_buffer->rgb_frame->width/height` directly — the same real,
  undownscaled source `ai::ConvertToMat` reads before scaling down — rather than hooking
  `src/ui/screen.cpp`'s rotation path as originally speced; this works under `--no-display` too
  (`Screen` is never constructed there) and picks up a rotation automatically since `rgb_frame`
  changes size whenever the decoder produces a differently-sized frame. Only re-sends when the
  value actually changes, tracked via `last_resolution_width/height`.
  **Real build error hit and fixed**: those two tracking fields were first added as `private`,
  which broke `AgentManager`'s use as an aggregate (`irobot_core.cpp` constructs it with designated
  initializers, `{.video_buffer = ..., .controller = ...}`) — C++ forbids private non-static data
  members on an aggregate. Fixed by making them public, matching the class's existing all-public
  data-member style. Rebuilt via the known-working CLion/MinGW recipe and confirmed the full binary
  links and runs.
  **Compatibility fix needed alongside it**: `agent_client.py`'s `stream` command reshapes every
  blob buffer as image pixels with no type check; a zero-length pixel payload (this new message)
  would have crashed it with a numpy reshape error. `record`/`interactive` were already safe (they
  filter to `BLOB_MSG_TYPE_OPENCV_MAT` only). Fixed by making `stream` print the resolution and
  skip non-image buffers instead of trying to display them.
- **Python**: `LiveConnection._read_loop()` (`connection.py`) now also captures
  `BLOB_MSG_TYPE_RESOLUTION` into `latest_resolution()`. `MainWindow._reconcile_detected_resolution()`
  (`main_window.py`), polled alongside the frame timer: auto-fills `Reference width/height` when
  unset and logs it; on a *mismatch* against an already-set value, logs a loud warning but
  deliberately does **not** silently overwrite it — every already-placed event's `(x, y)` is only
  meaningful relative to whatever reference resolution was in effect when it was clicked, so
  silently changing that value out from under existing events would silently invalidate them. An
  "Apply Detected Resolution" button lets the user opt in explicitly instead. Both paths (auto-fill
  and the button) reuse the `_loading_fields` guard from §7's second bug, since they also populate
  the spin boxes programmatically. Verified end-to-end with a fake TCP server standing in for
  `irobot`: the exact `BLOB_MSG_TYPE_RESOLUTION` wire bytes parse into `latest_resolution()`
  correctly, an unset project auto-fills both the model and the spin boxes, and a mismatched
  already-set project logs the warning exactly once (not once per poll tick) without touching the
  stored value.

This doesn't retroactively fix miscalibrated *event coordinates* in an existing project (those
were clicked against whatever the canvas showed at the time, which is unaffected by this change);
it fixes not being able to tell, and not being able to trust, what `Reference width/height` should
be set to in the first place.

## 7. Known bugs found and fixed during implementation

Every bug on this page (here, in §3.1, §6.1, and §6.2) was caught by actually exercising the tool
— an offscreen Qt smoke test, a fake-server wire-format check, a real C++ rebuild, or real use
against a device — not by inspection. Worth recording since they'd otherwise have been silent
correctness bugs:

- **`PrimitiveEvent.to_dict()` dropped `x=0`/`y=0`.** An early implementation filtered "falsy"
  fields out of the serialized dict to keep YAML terse; `0` is a legitimate corner-of-screen
  coordinate, not an absent one, so it was being round-tripped away. Fixed by listing exactly
  which fields are optional (`pointer_id`, `keycode`, `key_name`, `frames`) instead of a generic
  falsy-value filter; covered by `test_round_trip_preserves_zero_valued_position`.
- **Opening a project silently zeroed its reference resolution.** `_load_project_into_fields()`
  sets form widgets one at a time; each `QSpinBox.setValue()` fires `valueChanged`, wired to
  `_sync_project_fields()`, which reads *all* the spin boxes back into `self.project` — including
  ones the load loop hasn't reached yet. Loading `examples/mario_platformer.yaml` (reference
  1161px tall) reproducibly left `project.reference_height == 0` after the call. Fixed with a
  `self._loading_fields` guard flag that makes `_sync_project_fields()` a no-op while
  `_load_project_into_fields()` is populating the form. Reproduced and verified fixed via an
  offscreen (`QT_QPA_PLATFORM=offscreen`) smoke test instantiating `MainWindow`, loading the
  example project, and asserting `reference_width`/`reference_height` survive the round trip.
- **`AgentManager` broke as an aggregate.** See §6.2 — private data members on a class constructed
  with designated initializers is a compile error, not a runtime bug, but it's recorded here for
  the same reason: caught by actually trying to build, not by reading the diff.

## 8. Worked example

`tools/irobot_gym_ide/examples/mario_platformer.yaml` — calibrated (approximately, from the
screenshot that motivated this tool, not a real device) for a platformer with a fixed d-pad
(`move_left_start`/`move_left_stop`, `move_right_start`/`move_right_stop`, pointer 0, shared and
mutually exclusive), a jump button (`jump` a tap, `long_jump` a `PRESS`→`WAIT(20)`→`RELEASE`
macro, pointer 1), and an attack button (`attack`, pointer 2). Loads cleanly with zero validation
warnings and zero orphaned releases — see `tests/test_io.py` and the manual check in §7.

## 9. Setup / usage

```bash
pip install -r tools/irobot_gym_ide/requirements.txt   # PySide6, PyYAML, numpy
tools\irobot_gym_ide.cmd     # Windows
tools/irobot_gym_ide.sh      # Git Bash / WSL / Linux / macOS
```

Same resolve-their-own-working-directory pattern as `agent_client.cmd`/`.sh` (both `cd` into
`tools/` before running `python -m irobot_gym_ide.app`, since that's what makes the package
importable, then invoke `py -3` in preference to plain `python` for the same broken-shebang-stub
reason `agent_client.cmd` documents). **Found while wiring this up**: this dev machine has two
separate Python installs, and the interpreter `py -3` resolves to was not the one the
`pip install` above had been run against — the launcher ran fine but hit
`ModuleNotFoundError: No module named 'PySide6'`. Not a launcher bug; just a reminder that
`pip install -r requirements.txt` needs to target whichever interpreter the launcher actually
invokes on a given machine (run it via `py -3 -m pip install ...` if `.cmd`'s `py -3` path is the
one that's missing packages). Equivalent direct invocation, if you'd rather skip the launcher:
`python -m irobot_gym_ide.app` run from inside `tools/`.

Open `examples/mario_platformer.yaml` via File → Open Project to see a populated project without
a device connected (the canvas stays blank until you Connect). Against a real `irobot` process,
set Host/Port to match its `--port` (control = port+1, video = port+2, same convention as
`agent_client.py`). **Reference width/height must equal irobot's real negotiated resolution
exactly**, per §6.2 — as of this session's build, connecting auto-fills it for you (an unset
project) or warns you about a mismatch (an already-set one) via the `BLOB_MSG_TYPE_RESOLUTION`
message, so this is no longer a manual "read irobot's stdout" step for a build that includes it.
An older `irobot.exe` predating this change simply never sends that message, in which case
`_reconcile_detected_resolution()` silently does nothing (`latest_resolution()` stays `None`) and
you're back to reading it off the console yourself ("Initial texture: WxH") and typing it into
Reference width/height, exactly as `agent_client.py --screen-size` still requires today.

## 10. Testing

```bash
python -m unittest discover -s tools/irobot_gym_ide/tests -t .
```

25 tests, all pure-Python (`model.py`/`io.py`/`device_recorder.py` round-trips, validation, and
parser logic) — no Qt, no socket, no device required. GUI code is covered separately by manual
offscreen smoke tests (`QT_QPA_PLATFORM=offscreen`, see §7) rather than an automated suite;
formalizing those into `pytest-qt` tests is listed under Phase 2/backlog below rather than built
speculatively now.

## 11. Record from Device — real touches, not injected ones

`agent_client.py record` / irobot's own `Ctrl+E` already record touches, but only ones the
*desktop* injects through the mirror — clicking the SDL window or this IDE's own canvas. Neither
sees a touch made by a finger directly on the physical screen; that never passes through irobot's
socket protocol at all. `device_recorder.py` adds a second, independent capture path for exactly
that case, verified live against a real device before writing a line of the GUI: `adb shell
getevent -lt` reads the raw Linux input event stream straight off the touchscreen's kernel driver
(`synaptics_tcm_touch` on the test device), producing clean, complete, sub-millisecond-timestamped
down/move/up cycles regardless of what app is running or how the phone is held. No `irobot_server`
change, and no monorepo restructuring, is needed for this — it was a live open question when this
feature was scoped, resolved by the same capture.

**Parsing** (`TouchStateMachine`, fed one line at a time via `feed_line()`): reconstructs Android's
Type-B multitouch protocol (`ABS_MT_SLOT` selects which finger's subsequent `ABS_MT_TRACKING_ID`/
`ABS_MT_POSITION_X/Y` apply to; a `SYN_REPORT` closes out one frame of changes), with a protocol-A/
single-touch fallback (bare `ABS_X`/`ABS_Y` + `BTN_TOUCH`) for devices that never emit slot/tracking
events. Pinned against a verbatim excerpt of the real capture in `tests/test_device_recorder.py`,
not synthetic data, plus a synthetic two-finger case to prove slot demuxing doesn't leak one
finger's position into another's.

**Raw-to-reference-resolution scaling** (`gesture_to_events`): the touch panel's raw coordinate
range is *not* always the same as the announced screen resolution (§6.2), so it's probed
separately via `adb shell getevent -pl` (`parse_axis_ranges`, matched to the device block whose
name contains "touch") before being used to scale. On the test device the two ranges were within a
pixel of each other (1199×2669 raw vs. 1200×2670 reported), but the code never assumes that.

**Segmentation** (`segment_into_gestures`): groups the flat, possibly-interleaved (multiple
concurrent fingers) touch stream into per-finger down→…→up runs. Each gesture then becomes either
a single `TAP` (movement under `tap_threshold_px`, in raw units) or a `PRESS`→`MOVE`…→`RELEASE`
sequence with `WAIT` gaps reflecting the *real* recorded timing between samples (same `FRAME_MS`
assumption `connection.py`'s own `WAIT` playback already makes — see the backlog note below). No
downsampling of a long drag's samples is done; every recorded point becomes its own `MOVE` event,
trimmed by hand via the inspector if that's excessive for a given gesture.

**GUI flow** (`main_window.py`, "Record from Device" button, left panel): requires a reference
resolution (reuses `_require_reference_resolution()`) since recorded coordinates need scaling into
it just like a canvas click's do. On start, probes axis ranges and rotation once and blocks with a
clear reason if either can't be determined (rather than guessing). On stop, segments the capture,
logs a one-line summary of each detected touch, then merges **all of them into a single Action**
via `merge_gestures_into_events()` — **one recording session = one action**, prompted for a name
once. This is deliberate, not incidental: a real combo like "hold right while tapping jump" is
naturally two concurrent touches, and forcing a separate name onto each (an earlier version of this
feature did exactly that) makes it impossible to represent the combo as one action at all — you'd
get a `hold_right` action and a `jump` action, never a `right_jump` action that does both. If a
session genuinely contains touches meant as separate actions, record them in separate start/stop
sessions instead. New actions reuse the same pointer-conflict/orphan-release checks (§3.1) every
other action gets.

Two decisions inside the merge are worth being explicit about:

- **Chronological, not gesture-grouped, ordering.** If touch B starts before touch A finishes, the
  merged event list interleaves them by real timestamp (`merge_gestures_into_events` collects every
  gesture's `(t, PrimitiveEvent)` pairs into one list and sorts once), not "all of A's events then
  all of B's" — the whole point of recording a combo is that the *timing relationship* between the
  touches is what makes it a combo.
- **A held-but-motionless finger is not a tap.** The original tap/drag classifier
  (`_gesture_to_timed_events`) judged only by movement distance — a finger held still for 200ms
  and a finger tapped for 20ms both showed zero movement, so both became an instant `TAP`. That
  silently destroys a hold's actual duration, which is exactly the "right" half of "hold right,
  tap jump." Fixed by also checking duration (`tap_duration_s`, default 150ms): movement *or*
  duration past its threshold routes a gesture to `PRESS → [MOVE...] → RELEASE` instead of a bare
  `TAP`. Verified with a case built specifically to catch the old bug: a 200ms zero-movement hold
  now produces `PRESS`/`WAIT`/`RELEASE`, not `TAP` (`test_held_still_finger_becomes_press_release_
  not_a_tap`), while a genuinely brief zero-movement touch still correctly stays a plain `TAP`
  (`test_brief_still_touch_stays_a_tap`) — confirmed end-to-end through the actual GUI flow too,
  not just the library function.

**Verification, in three separate layers** since no single test exercises the whole chain against
real hardware: (1) the pure parser against a verbatim real-device capture excerpt (proves the
*parsing* is correct); (2) `DeviceEventRecorder`'s `Popen`+background-thread plumbing against a
fake process emitting known lines with real timing gaps (proves the *live streaming* mechanics are
correct, independent of whether a human touch happens to land in a given test window); (3) an
offscreen Qt smoke test driving the full GUI flow (button → fake recorder → stop → dialog → new
`Action`) with the recorder's `adb` call swapped for the same fake process. What was **not**
separately proven is a real finger touch flowing through the complete class end-to-end in one shot
— worth being explicit about, since (1) and (2) each independently cover the two halves that
compose it, but weren't combined in a single live-hardware run. `adb shell input tap` was tried as
a way to generate a deterministic touch for testing and turned out **not** to be a valid stand-in:
it injects at Android's software input layer, not through the physical digitizer driver, so
`getevent` never sees it — a real finding, not a tooling detail, since it means this capture path
is specifically about genuine hardware touches and cannot be exercised by any `adb input`/UI-
automation command.

### 11.1 The rotation bug: raw touch-panel axes aren't the display's axes

Reported after first real use: a recorded "jump" button came out at roughly `(274, 1107)`; the
button's actual location is roughly `(2416, 1073)`. Root cause, confirmed with `adb shell dumpsys
input` against the real device: this phone's touch digitizer is natively **portrait** (raw
`ABS_MT_POSITION_X/Y` max `1199×2669`, matching §11's already-probed axis ranges), but the game
was displaying **landscape**, and Android's `InputReader` rotates every raw touch sample by the
display's current rotation before it becomes a `MotionEvent` — the same logical space
`CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT`'s target coordinates live in. `gesture_to_events` did a naive
independent per-axis linear scale (`raw_x → ref_w`, `raw_y → ref_h`) with no rotation step at all,
which is exactly wrong whenever raw and logical axes don't line up 1:1 — not an approximation
error, a category error (right ballpark of numbers, wrong axis pairing).

**Fix**: `parse_touch_rotation()` reads the *actual currently-applied* rotation (0/1/2/3 =
`Surface.ROTATION_0/90/180/270`) from `adb shell dumpsys input`'s `Viewport INTERNAL` line, queried
fresh every time a recording starts (rather than hardcoded once, since orientation can change
between sessions) — probing failure now **blocks** recording with a clear reason, same
refuse-rather-than-guess policy as an unset reference resolution. `apply_rotation()` applies the
matching transform (four cases, one identity) to each raw sample *before* `gesture_to_events`
scales it into the reference resolution; the scaling denominators swap for a 90°/270° rotation too
(the "logical width" after rotation is the raw panel's Y-range, not its X-range), which is exactly
what made the old bug read as "the X coordinate looks flipped" — it's actually an axis swap plus a
flip on one axis, not a pure mirror, which is why a naive `screen_width - x` guess (which is
roughly what a quick manual look at the wrong numbers suggests) wouldn't have generalized to other
rotations or devices either.

**Verified against the real regression case**, not just derived on paper: the last raw touch state
cached in `adb shell dumpsys input`'s `AbsState` after the actual mis-recorded jump tap was `raw
(123, 2462)` — applying the fix's rotation transform and scaling into this device's real `2670×1200`
resolution lands at `(2462, 1076)` scaled appropriately to `~(2471, 1077)`, a few percent from the
reported true location `(2416, 1073)` and comfortably inside a button's touch radius, versus the
old code's `(274, 1107)`, which was off by an entire screen dimension. Both the pure-formula case
(`ApplyRotationTest`) and the full `gesture_to_events` path (`GestureToEventsTest`) pin this exact
raw coordinate as a regression test. `probe_rotation()` was additionally confirmed live against the
real device (`rotation: 1`, i.e. `ROTATION_90`, matching the dumpsys output that diagnosed the bug),
and the full GUI flow was re-run offscreen with the same raw coordinates through
`_toggle_device_recording()`/`_finish_device_recording()`, confirming the fix holds through the
actual code path a user hits, not just the underlying library function.

## Phase 2 (not yet built) — reward / score extraction

Deferred exactly as scoped ("let's first focus on action definitions"). When picked up, it should
be a GUI author for `docs/opengym_implementation_plan.md §8`'s already-designed signal tiers, not
a new design:

- A `RewardSignal`/`TerminalSignal` editor per project, discriminated on `source: logcat | ocr`.
- `logcat`: a regex + the project's `serial`, shelling out to `adb logcat` — no new wire protocol,
  matches plan §8.3.1/§8.4.1.
- `ocr`: an ROI rectangle drawn on the same live-frame `CanvasView` used for action regions (the
  reason `QGraphicsView` was chosen over a lighter toolkit, per §2) plus an extractor choice
  (`digit_template` / `icon_state` / `tesseract` / `region_changed` / `health_bar_fill`, plan
  §8.3/§8.3.6) — ideally with the live-preview-while-dragging UX described when this phase was
  scoped ("as you drag the rectangle, show what the extractor reads from that exact crop").
- Extractor implementations registered by name (plan's plugin-registry suggestion) rather than a
  hardcoded dropdown, so a project-specific extractor is a drop-in file.

## Other deferred/backlog items (not built, noted for a future pass)

- **Multiple projects open at once** — today the window holds exactly one `Project`; a real
  project-tree explorer (open several games, switch between them) is a natural follow-on once
  Phase 2 makes a single project's editing surface bigger.
- **Recording-assisted action discovery — implemented, via §11's "Record from Device", not the
  originally-discussed `Ctrl+E`/`agent_client.py record` import.** That alternate source (clustering
  *injected* tap coordinates from a mirror-driven session) is still undone and would be a smaller
  addition on top of the same `segment_into_gestures`/naming-dialog flow if ever wanted — the two
  differ only in where the raw touch coordinates come from.
- **`WAIT` frame timing is an assumed constant** (`FRAME_MS = 33`, i.e. ~30 fps) in
  `connection.py`, also relied on by §11's recorded-gesture timing — there's no real frame-rate
  handshake on the wire yet, so both a `WAIT(frames=20)` macro like `long_jump` and a recorded
  drag's inter-sample gaps are timed by wall-clock sleep/estimate, not by actually counting
  delivered video frames. Fine for today's manual calibration use; worth revisiting if frame
  delivery rate proves far from 30 fps in practice.
- **A long recorded drag produces one `MOVE` event per raw sample, unsimplified** — `getevent` can
  emit updates every few milliseconds, so a slow one-second drag could become 50+ events. No path
  simplification (e.g. Douglas-Peucker) is applied; trim via the inspector's remove/reorder buttons
  if a specific recording is excessive. Not built speculatively without a concrete case needing it.
- **`calibrate_buttons.py`** (referenced in plan §7.4 as a possible standalone script) is
  effectively superseded by this GUI's click-to-add flow — not built separately.
