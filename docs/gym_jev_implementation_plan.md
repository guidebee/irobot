# Gym Environment + TypeSafe Jev Integration — Detailed Implementation Plan

Status: **plan, not yet implemented** (written 2026-09-27). Supersedes the build order in
[`opengym_implementation_plan.md` §12](opengym_implementation_plan.md#12-suggested-build-order-each-step-independently-mergeabletestable)
and extends [`irobot_gym_ide_design.md`](irobot_gym_ide_design.md) with a TypeSafe Jev integration.
It does **not** replace those two documents' design rationale: they remain the reference for
*why* (protocol analysis, AndroidEnv comparison, reward-tier ordering). This document is the
reference for *what gets built, in what order, and how we know each piece is done*.

It came out of a peer review of both documents (see
[`opengym_implementation_plan.md` §15](opengym_implementation_plan.md#15-peer-review-2026-09-27) and
[`irobot_gym_ide_design.md` §14](irobot_gym_ide_design.md#14-peer-review-2026-09-27)) and the
`typesafe_agent/` prototype (`typesafe_agent/README.md`). Where this plan disagrees with an earlier
document, the disagreement and its reason are stated inline, not silently overridden.

---

## 0. Summary

**Goal.** Let three kinds of "player" drive a real Android game through `irobot`, against **one
shared contract** for actions, observations, rewards, and episode boundaries:

| Driver | What it is | Exists today? |
|---|---|---|
| **Scripted** | A Gym IDE Game Run graph, replayed deterministically | Yes (`run_engine.py`) |
| **RL policy** | A Stable-Baselines3 (or similar) policy trained against a Gymnasium env | No: no `env.py` yet |
| **Jev policy** | TypeSafe's Jev model choosing actions from structured game state | Prototype (`typesafe_agent/`) |

The first target game is **Ampere's Run** (the Mario-style platformer in `guidebee/super-morse`),
because the `mario_platformer` example project is already calibrated against it, and because we own
its source. Owning the source changes what's possible, as decision D4 below explains.

**The ten decisions this plan commits to** (details in §3):

| # | Decision | Replaces / resolves |
|---|---|---|
| D1 | The env is **real-time**: fixed control rate, actions held between steps, observation age reported | Implicit "world pauses between `step()` calls" assumption in the plan's §9 |
| D2 | Action spaces are encoded as **`Discrete`/`MultiDiscrete`** (SB3-compatible), with a named view on top | Plan §7.3–7.4's `Dict` action spaces, which SB3 cannot train |
| D3 | Observations have a **fixed canonical shape**, plus an optional structured `features` dict | Plan §6's device-dependent `Box` shape |
| D4 | Structured state comes from a **ranked source list**: first-party telemetry, then vision features, then pixels | Jev's current near-blind observation in `typesafe_agent` |
| D5 | Each game is defined by **one declarative `task.yaml`** in the IDE project directory | Plan §14.3's open "no declarative task artifact" gap |
| D6 | Jev runs as an **asynchronous policy** with delay compensation, a deterministic fallback, and a decision log | The prototype's blocking loop |
| D7 | Jev may appear inside a Game Run only as a **`DECIDE` node** with a timeout, a fallback edge, and record/replay | `GAME_RUN_AI_ASSIST_DESIGN.md` §3.3's rejection of live LLM nodes, now reconciled |
| D8 | For owned games, a **simulator backend** shares the device env's contract | Plan §1.1.3's throughput problem |
| D9 | Schemas carry time in **milliseconds**, and "frame" is always qualified | Three different meanings of "frame" in the code today |
| D10 | A shared **transport package** (`irobot_client/`) is extracted before the env is built | `_agent_client.py`'s importlib shim; plan §5's `protocol.py` |

**Phase 0 is a gate, not a formality.** `irobot_gym_ide_design.md` §13 records an unresolved bug:
a structurally clean replay sometimes has *no effect on the device*, with no error anywhere in the
pipeline. No agent, whether scripted, RL, or Jev, can be evaluated while that's open. It gets
root-caused first (§4, WP0.1).

---

## 1. Scope

### 1.1 In scope

- A Gymnasium env over the AgentManager sockets (device backend), plus a simulator backend for
  Ampere's Run.
- A declarative task definition (`task.yaml`), plus the reward/terminal/reset signals it references.
- TypeSafe Jev as a policy over that env, and as an IDE feature (an Agent tab, a `DECIDE` node,
  trace-to-Game-Run compilation).
- First-party telemetry for Ampere's Run (a debug-only change in `guidebee/super-morse`).
- An evaluation harness that compares the scripted, heuristic, Jev, and PPO drivers on the same
  metrics.

### 1.2 Out of scope (unchanged from existing docs unless noted)

- Live/PvP games, anti-cheat evasion (plan §1.1.4).
- Audio observations (plan §6).
- Distributed training infrastructure beyond "N processes on one host" (plan §10).
- Any change to TypeSafe itself. This plan consumes `typesafe-sdk` as a black box. §13.2 lists what
  we don't yet know about it.

### 1.3 Non-goals, stated explicitly because they're tempting

- **Not** making Jev a vision model. Jev consumes structured JSON (see `typesafe-mario`'s README:
  "The model does **not** receive screenshots"). Every piece of structure it sees must be computed
  by code first. That's a feature, not a limitation to work around: exact timing arithmetic stays
  in code, and Jev interprets typed facts.
- **Not** folding Jev into the deterministic Game Run executor, except via the D7 `DECIDE` node,
  which keeps replays reproducible.

---

## 2. Baseline: what exists on 2026-09-27 (verified against source)

| Area | State | Where |
|---|---|---|
| Control framing | **Length-prefixed, done.** 4-byte big-endian prefix; oversize frame drops the connection | `src/agent/agent_controller.cpp` `ProcessMessages` (`kFrameHeaderSize = 4`); `tools/agent_client.py` `send_json` |
| Resolution announcement | Done | `BLOB_MSG_TYPE_RESOLUTION`, `AgentManager::SendResolution` |
| Agent video rate | **Capped at ~15 fps** (`kMinVideoSendIntervalMs = 66`) | `src/agent/agent_manager.cpp:64` |
| Headless mode | Exists (`--headless`), idle-waits instead of busy-spinning | `src/core/irobot_core.cpp` |
| Live connection + action execution | Done: frame reader thread, held-pointer bookkeeping, resolution rescale | `irobot_gym_ide/connection.py` |
| Game definition | Actions (with `ActionKind`), HUD regions and combos, image templates, Game Runs, sessions | `irobot_gym_ide/model.py`, `io.py` |
| Game Run executor | 6 node kinds (ACTION, DELAY, REPEAT, COMPARE, FIND_TEMPLATE, ASSERT); fork/join | `irobot_gym_ide/run_engine.py` |
| Dry run | Done | `irobot_gym_ide/dry_run.py` |
| ActionMap export | Done (Tier 1.5 schema + `compound_macros`) | `irobot_gym_ide/gym_export.py` |
| Reward / Observation / Reset panels | **Stubs** ("coming soon") | `irobot_gym_ide/gui/panels/{reward,observation,reset}_panel.py` |
| Gym env | **Not built** | — |
| Jev prototype | Blocking decide→act loop, phash-only observation, heuristic fallback, latency benchmark | `typesafe_agent/` |
| Tests | 237 in `irobot_gym_ide/tests` (17 skipped), 11 in `typesafe_agent/tests` | — |
| **Open P0 bug** | Replay sometimes has no device effect, with no error anywhere | `irobot_gym_ide_design.md` §13 |

**Three different "frames" in the code today** (the root of D9):

| Name | Duration | Where it's defined |
|---|---|---|
| Game physics frame | 16.7 ms of *game time*. Ampere's Run is variable-timestep: each render's delta is scaled into 60 Hz physics units (`PHYSICS_FPS = 60f` in several actor classes) and clamped to at most 1/30 s per render (`MarioConfiguration.MAX_DELTA_SECONDS`) | super-morse game engine |
| `WAIT`/`DELAY` frame | 33 ms of wall-clock time (`FRAME_MS = 33`) | `irobot_gym_ide/connection.py:27` |
| Agent video frame | ≥66 ms (throttle) | `src/agent/agent_manager.cpp:64` |

The delta clamp has a consequence worth stating: **whenever the device renders below 30 fps, game
time runs slower than wall-clock time.** Any schedule computed in game time (the methodology doc's
simulator) then drifts against wall-clock `WAIT` delays. That's the mechanism behind
`Project.time_scale`, and it's why telemetry (WP5.1) reports accumulated game time, not just a
wall-clock timestamp.

`level_1_1_clear`'s delays are in `WAIT` frames (33 ms), while `game_run_design_methodology.md`
computes its schedule in *game physics* frames (16.7 ms). That's only correct if someone converted
between the two when writing `runs.yaml`, which should be checked, not assumed (WP0.4).

---

## 3. Architecture

### 3.1 Layers

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Drivers         GameRunExecutor      SB3 / CleanRL           JevPolicy             │
│                 (scripted)           (RL)                    (TypeSafe)            │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Env             irobot_gym.IrobotEnv  (gymnasium.Env, real-time)                    │
│                   ├─ backend: DeviceBackend  (AgentManager sockets)                │
│                   └─ backend: SimBackend     (owned games only, e.g. Ampere's Run) │
│                 ActionCodec · ObservationBuilder · SignalRunner · Health/Relaunch  │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Game definition irobot_gym_ide.model / io   (project.yaml, actions.yaml, hud.yaml, │
│                 templates.yaml, runs.yaml,  + NEW task.yaml)                       │
│                 irobot_gym.signals.*  (registry: template, phash_stuck, icon_state,│
│                 health_bar, digit_template, scroll_progress, telemetry, logcat)    │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Transport       irobot_client.protocol  (wire encode/decode, ONE implementation)   │
│                 irobot_client.connection (LiveConnection, moved from the IDE)      │
│                 irobot_client.telemetry  (adb logcat tail, owned-game channel)      │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Device          irobot (C++): AgentManager control port +1 / video port +2         │
│                 irobot-server (APK): PointersState, InputManager.injectInputEvent  │
│                 Game APK (+ optional debug telemetry emitter, owned games only)    │
└──────────────────────────────────────────────────────────────────────────────────┘
Tooling across layers: Gym IDE (authoring, supervision), typesafe_agent CLI, eval harness.
```

### 3.2 Package layout (target)

```text
irobot_client/                 # NEW (WP1.1): headless transport, zero Qt, minimal deps
├── protocol.py                #   moved out of tools/agent_client.py; agent_client imports it
├── connection.py              #   moved from irobot_gym_ide/connection.py (IDE re-exports it)
├── telemetry.py               #   TelemetryTail: `adb logcat` reader → parsed JSON records
└── tests/                     #   byte-fixture protocol tests, fake-server connection tests
irobot_gym_ide/                # existing; model/io stay here; gains task.py + panels
irobot_gym/                    # NEW (WP3.x): the env; top-level, not tools/irobot_gym/
├── env.py                     #   IrobotEnv
├── backends/{device,sim}.py
├── codec.py                   #   ActionCodec (D2)
├── observation.py             #   ObservationBuilder (D3)
├── signals/                   #   registry + built-in signals (WP2.2)
├── health.py                  #   §9.1-style health tracking and bounded relaunch
├── wrappers.py                #   ActionHistory, TimeLimit defaults, recording
├── registration.py            #   gymnasium.register(...)
└── tests/
typesafe_agent/                # existing prototype; becomes a thin driver over irobot_gym
├── state/                     #   NEW: Jev state builders (telemetry, vision, pixels-only)
├── policy.py                  #   JevPolicy (async), HeuristicPolicy
├── trace.py                   #   decision log + trace→GameRun compiler
└── ...
eval/                          # NEW (WP6.3): driver-comparison harness + report
```

**Why top-level `irobot_gym/`, not the plan's `tools/irobot_gym/`:** the repo already settled on
top-level Python packages run via `python -m <pkg>` from the repo root (`irobot_gym_ide/`,
`typesafe_agent/`). `tools/` holds `agent_client.py` as a script, not a package. Following the
established convention avoids a second import-path scheme.

### 3.3 Key design decisions

#### D1 — The env is real-time

Gymnasium's API implicitly assumes the world pauses between `step()` calls. A real device does
not. Without an explicit policy about time, the MDP the agent learns changes with the policy's own
inference speed: a slower policy sees larger state jumps between decisions. That makes training on
one machine and evaluating on another quietly different problems. This is the framing of
Ramstedt & Pal, *Real-Time Reinforcement Learning* (NeurIPS 2019). The standard remedy for a known,
bounded delay is to augment the state with the actions still in flight (Katsikopoulos &
Engelbrecht, 2003, on delayed MDPs).

Concretely:

- **Fixed control period.** `IrobotEnv(control_period_ms=...)` defines one step as a fixed
  wall-clock slot. `step(a)` applies `a`, sleeps until the slot's deadline, then returns the freshest
  observation. Default: `control_period_ms = 133` (2 × the 66 ms agent-frame throttle), so every step
  is guaranteed at least one fresh frame. Tune from WP0.3's measured numbers.
- **Actions are held, not pulsed.** Hold-type buttons stay in their commanded state until a later
  action changes them. This matches how both the Tier 1.5 schema (§7.4 of the plan) and the IDE's
  `*_start`/`*_stop` actions already behave.
- **Overruns are counted, not hidden.** If the caller takes longer than one slot between `step()`
  calls, the env doesn't pretend otherwise. `info["overrun_ms"]` and `info["missed_slots"]` report it,
  and in `strict` mode a missed slot repeats the previous action (AndroidEnv's `REPEAT` idea).
- **Delay is observable.** `info["obs_age_ms"]` (time since the frame was received) and
  `info["action_latency_ms"]` (for backends that can measure it, see D4 telemetry) are always
  present. An optional `ActionHistory(k)` wrapper appends the last *k* actions to the observation,
  which is the delayed-MDP augmentation mentioned above.
- **Async policies are first-class.** Jev (D6) and any other slow policy should run *beside* the
  control loop, not inside it: the env keeps stepping with the last committed action while inference
  is in flight. `typesafe-mario` already does exactly this (`runner.py`'s `ThreadPoolExecutor`,
  holding `active_decision` until `pending.done()`). `irobot_gym` provides this pattern as
  `AsyncPolicyRunner` so each driver doesn't reimplement it.

#### D2 — Discrete/MultiDiscrete action encoding, named view on top

Stable-Baselines3 supports `Box`, `Discrete`, `MultiDiscrete`, and `MultiBinary` action spaces
(algorithm-dependent: PPO/A2C take all four, DQN only `Discrete`). It does **not** support `Dict`
action spaces, and it has no support for the hybrid discrete-plus-continuous action space the plan's
Tier 0.1 describes (that's a parameterized-action problem needing specialized algorithms). So the
plan's Tier 0.1, 1, and 1.5 as written cannot be trained with the plan's own named training library.

Fix: an `ActionCodec` owns the translation between three representations.

1. **Encoded** (what the policy sees): `Discrete(n)` or `MultiDiscrete([...])`.
2. **Named** (what humans, logs, and Jev see): `{"dpad": "right", "jump": "tap", "run": "hold"}`
   or a single macro name.
3. **Wire** (what gets sent): `PrimitiveEvent`s emitted only on state *transitions*, per plan §7.4.

For Tier 1.5 (the default for gamepad games), the codec groups HUD regions by **pointer id**,
because regions sharing a pointer are mutually exclusive (one thumb). Each group becomes one
`MultiDiscrete` dimension:

| Dimension | Pointer | Values (mario_platformer) |
|---|---|---|
| `dpad` | 0 | `none, left, right, up, down` |
| `jump` | 1 | `none, tap` (`long_jump` stays a macro, below) |
| `run_fire` | 2 | `none, tap(fire), hold(run)` |

This gives `MultiDiscrete([5, 2, 3])`: 30 combinations, with invalid combinations impossible by
construction rather than filtered at runtime. **Macros** (`long_jump`, `compound_macros` from
`gym_export.py`) are exposed through a separate `Discrete` "macro" dimension whose value 0 means "no
macro". While a macro runs, the other dimensions are ignored and the macro's frames are summed into
one step's reward, per plan §7.4's macro-step semantics.

`gym_export.export_action_map` already produces the input the codec needs (buttons with
`pointer_id` and `press_modes`, plus macros). The codec is a consumer of that export, not a second
schema.

Tier 0 (grid tap) stays as specified: it's already `Discrete`. Tier 0.1 and Tier 1 remain
documented extension points, with the note that they need either a flattening codec or a
parameterized-action algorithm.

#### D3 — Fixed canonical observation, plus optional structured features

`BLOB_MSG_TYPE_OPENCV_MAT` is "≤800 px on the long side", so its shape depends on the device's
aspect ratio, and it changes on rotation. A Gymnasium `Box` must have a fixed shape. Also, SB3's
`NatureCNN` is designed for the Atari-standard 84×84, and an 800 px frame makes the first conv
layer needlessly expensive.

Observation contract:

```python
observation_space = spaces.Dict({
    "pixels":   spaces.Box(0, 255, (H, W, C), np.uint8),   # canonical size, set per task
    "features": spaces.Box(-inf, inf, (F,), np.float32),   # optional; present if task declares features
})
# or plain Box "pixels" when the task declares no features (keeps SB3 CnnPolicy usable as-is)
```

- **Canonical size**: resized, letterboxed to preserve aspect ratio, default 84×84 grayscale.
  Declared in `task.yaml`.
- **Rotation**: a resolution change mid-episode ends the episode with `truncated=True` and
  `info["truncation_reason"] = "rotation"`, instead of silently producing a differently-shaped frame.
- **Features**: a flat, fixed-length vector built from the task's declared structured sources (D4),
  for example player x/y/vx/vy, the nearest three enemies' relative positions, and gap distance. The
  same values are also reported *by name* in `info["state"]`, which is what Jev consumes. RL gets
  numbers; Jev gets a named JSON object; both come from one computation.

This keeps plan §6's "raster-first, no object extraction in the env" position for the generic
case. It adds a *declared, optional* channel for games where structure is available cheaply, which
for an owned game with telemetry it is. For an unowned game the channel is simply absent.

#### D4 — Ranked sources of structured state

Jev's quality depends almost entirely on the state it's given. `typesafe-mario` works because NES
RAM gives exact positions. The `typesafe_agent` prototype currently gives Jev only "did the screen
change", so it's choosing nearly blind. State sources, ranked by quality, mirroring plan §8's
"cheapest trustworthy signal first" ordering:

| Rank | Source | Available for | Quality | Cost |
|---|---|---|---|---|
| 1 | **First-party telemetry**: the game emits structured JSON (position, velocity, enemies, tiles ahead, lives, progress) | Games we own (Ampere's Run) | Exact, and gives true input→effect latency | A debug-only change in the game (WP5.1) |
| 2 | **Logcat regex** (plan §8.3.1) | Any game that happens to log | Sparse (usually score/level events only) | Minutes to find |
| 3 | **Vision features**: template matches (multi-match `FIND_TEMPLATE`), scroll progress, HUD signals | Any game | Approximate, 66 ms granularity | Per-game template capture in the IDE |
| 4 | **Pixels only** (phash change, stall count) | Any game | Near-blind | Free |

**Ampere's Run uses rank 1.** This is the one place where owning the game matters most, and it's a
different decision from the one made earlier in this project. The earlier decision chose *not* to
build an in-app debug bridge for **control**, because iRobot already injects real touches and that
path tests the real input stack. That decision stands. Telemetry is **observation only**: a
one-directional, read-only, debug-build-only stream. It does not replace or bypass iRobot's touch
injection, so every action still travels the real device input path.

#### D5 — One declarative `task.yaml` per game

Plan §14.3 flags the lack of a declarative, versionable task artifact comparable to AndroidEnv's
`Task` textproto, and §8.2 currently specifies `GameAdapter` as a Python class. Close that gap now,
before any adapter code exists to migrate: signals are **registry entries referenced by name** in a
YAML file that sits in the IDE project directory next to `actions.yaml`, matching the existing
split-file layout (`io.py`). §6.1 has the full schema.

The IDE's Reward, Observation, and Reset panels (currently stubs) become the authoring UI for this
file, which is exactly the "GUI author for plan §8's already-designed signal tiers" that
`irobot_gym_ide_design.md`'s Phase 2 section asks for.

#### D6 — Jev as an asynchronous, delay-compensated policy with a decision log

Concretely, `JevPolicy` follows the pattern `typesafe-mario` validated. Details are in §8.

- Inference runs off the control thread. The env keeps applying the last committed action.
- Each request includes measured delay (`reaction_timing`: action horizon plus last inference
  delay). Timing-critical facts are computed in code, not by the model. For example,
  `typesafe-mario`'s `jump_must_start_this_decision` combines the takeoff deadline, measured
  response age, and action cadence into one boolean.
- Every decision is logged with its full state, question set, answer, probabilities, latency, and
  outcome. That log is the evaluation record, the debugging record, and the input to the
  trace→Game Run compiler (D7).
- **Fallback is deterministic.** On timeout, error, budget exhaustion, or an answer outside the
  allowed set, the policy uses a configured fallback (default: hold the current action, or run the
  heuristic). It never raises into the control loop.

#### D7 — Jev inside Game Runs only as a `DECIDE` node, with record/replay

`GAME_RUN_AI_ASSIST_DESIGN.md` §3.3 rejects a live LLM node for two reasons: latency, and loss of
replay reproducibility. It also says what an acceptable version would look like: "a very
clearly-labeled node kind with its own timeout/fallback semantics." `DECIDE` is that node, with
**record/replay** added so the reproducibility objection is answered rather than accepted as a cost.

- `mode: live`: calls Jev, takes the chosen edge, and records the decision under key
  `(run, node_id, visit_index)`.
- `mode: replay`: reads the recorded decision and takes the same edge, with no Jev call. The run
  becomes exactly as deterministic as any other Game Run.
- `mode: live_or_replay`: replays if a recording exists, otherwise decides live.
- Timeout: take the `fallback` edge and record that the fallback fired.

The latency objection still holds for frame-perfect moments. The guidance (applied in §8.7) is to put
`DECIDE` only at *strategic* branch points (which route, whether to wait for an enemy to turn),
never at jump-timing points, which stay in deterministic nodes.

**Trace→Game Run compilation** extends the same idea. A successful live Jev playthrough's decision
log can be compiled into a plain Game Run of ACTION and DELAY nodes, which a human reviews and
saves. That turns "Jev found a way through" into a deterministic, reviewable, regression-testable
artifact. It fits `GAME_RUN_AI_ASSIST_DESIGN.md` §3's "AI as design-time co-author" principle, with
the AI's authoring done by playing rather than by drawing.

#### D8 — Simulator backend for owned games

Plan §1.1.3 correctly identifies real-device step throughput (single to low-double-digit steps per
second) as the ceiling on RL sample efficiency. For Ampere's Run there's a way around it:
`game_run_design_methodology.md` §3.2 already built a frame-accurate simulation from the game's
physics constants and level data, and §7 of that doc proposes turning it into reusable tooling.

`SimBackend` implements the same backend interface as `DeviceBackend`. It shares the task, the
action codec, and the feature definitions, so a policy trained in simulation runs on the device
unchanged:

- Pixels: rendered from tile data at canonical resolution (flat-shaded is fine at 84×84 grayscale),
  or omitted for feature-only training.
- **Latency randomization**: sample action delay and observation age from WP0.3's measured
  distribution so a policy trained in sim doesn't assume zero latency (standard domain
  randomization).
- Validation: WP5.3 checks the simulator against telemetry recorded from real play (the same
  trajectory in both, compared step by step).

The sim is a Python reimplementation, so it can drift from the Java game. Mitigations: the
telemetry comparison test runs in CI against checked-in recordings, and the physics constants file
cites the Java source lines it came from (the methodology doc's §3.1 discipline).

#### D9 — Milliseconds in schemas; "frame" always qualified

- New schema fields use `_ms` (for example `control_period_ms`, `timeout_ms`, `hold_ms`).
- Existing `frames` fields (`PrimitiveEvent.frames`, `RunNode.frames`) keep their meaning of
  `FRAME_MS` = 33 ms units, documented as **"WAIT frames"**, and `task.yaml` gains
  `timing.wait_frame_ms: 33` so the unit is declared where it's used rather than assumed.
- Telemetry reports **accumulated game time** (`gt_ms`) and a **render-frame counter** (`rf`)
  alongside the wall-clock timestamp, never a bare `frame`. Because Ampere's Run is
  variable-timestep (§2), game time and render count diverge whenever the device is slow, and both
  are needed to diagnose timing problems.

#### D10 — Extract `irobot_client/` before building the env

Today the wire protocol lives in a script (`tools/agent_client.py`) that the IDE loads through an
importlib shim (`_agent_client.py`). `LiveConnection` lives inside the IDE package even though it
has no GUI dependency. The env, the IDE, and `typesafe_agent` all need both. Extracting them first
is the plan's own §5 intent (`protocol.py`, "both import this"), done slightly more broadly:
connection and telemetry move too. `irobot_gym_ide.connection` becomes a one-line re-export, so no
existing import breaks.

---

## 4. Phase 0 — Gate: make the device path trustworthy

Nothing in Phases 3 to 7 can be evaluated honestly until the device reliably does what it's told
and we know how long that takes.

### WP0.1 — Root-cause the silent touch drop (P0 blocker)

- **Problem**: `irobot_gym_ide_design.md` §13. A clean 1050-event replay sometimes has no effect.
  Every C++ stage logs success. The remaining unlogged path is
  `irobot_server/.../wrappers/InputManager.java:48`, where `injectInputEvent(...)` can return
  `false` without throwing.
- **Steps** (continuing §13's "Next steps when resuming"):
  1. Log the plain-`false` return in `InputManager.injectInputEvent`, including the event's action,
     pointer count, and display id. Rebuild and push `irobot-server`.
  2. Reproduce with the failing replay. If it fires, compare `targetDisplayId`
     (`Controller.getEventPointAndDisplayId`, ~line 482) against the real focused display at
     replay time. A stale display id after reconnect is the leading hypothesis.
  3. If it never fires, the framework accepted every event, so check app focus and game state
     (for example, whether the game was paused or showing a dialog at the time).
  4. Run once with `--headless` removed, to eliminate the headless event-loop rewrite as a variable
     (step 4 of §13's list).
  5. Remove the temporary `log_level=verbose` from `device_server.cpp` once resolved.
- **Also add a counter, not just a log**: expose "events accepted / rejected by
  `injectInputEvent`" through the control channel's unused device→agent direction, or via logcat,
  so a future silent drop shows up as a number in `info` rather than a mystery.
- **Done when**: 10 consecutive full replays of `level1.session.yaml` each produce visible device
  effects, and the rejected-event counter reads 0 (or, if nonzero, each rejection has a logged,
  understood cause).

### WP0.2 — Documentation hygiene

- Update stale statements identified in review (listed in `opengym_implementation_plan.md` §15.1
  and `irobot_gym_ide_design.md` §14.1). Most importantly, fix `tools/README.md`'s protocol
  reference, which still says the control channel has "no length prefix or delimiter".
- Move dated session logs (`irobot_gym_ide_design.md` §12–13) into
  `docs/journal/2026-09-12-live-agent-bugs.md`, leaving a one-paragraph summary and link, so the
  design doc stays normative.
- **Done when**: every factual claim in both docs' "current state" sections matches the code, as
  checked against this plan's §2 table.

### WP0.3 — Measure real latency

- The `typesafe_agent latency-check` prototype times from action send to the next observed phash
  change. Two caveats to fix:
  - **Quantization**: frames arrive at most every 66 ms, so each sample has up to 66 ms of error.
    Report this, and for this measurement run irobot with a lower throttle if WP0.5 makes it
    configurable.
  - **Wrong-cause changes**: in a scrolling game, the screen changes constantly regardless of input,
    so a phash change doesn't prove the action caused it. Use a static screen (a pause menu, or the
    title screen where "tap" has a visible effect), or, once WP5.1 lands, use telemetry's echo of the
    input (the `cmd` field's edge, stamped with `gt_ms`, §9), which measures true input-to-game latency.
- Report p50, p95, and max over at least 50 samples, per device, and record results in
  `docs/measurements/latency.md` with the device model, connection type (USB or Wi-Fi), irobot flags,
  and git revision.
- **Done when**: numbers exist for at least one real device and one emulator, and D1's default
  `control_period_ms` is set from them.

### WP0.4 — Reconcile frame units in the worked example

- Already verified: physics runs in 60 Hz units (`PHYSICS_FPS = 60f`), with the per-render delta
  clamped to 1/30 s (`MarioConfiguration.MAX_DELTA_SECONDS`). See §2.
- Verify whether `level_1_1_clear`'s `DELAY` values were converted from physics frames (16.7 ms) to
  WAIT frames (33 ms). If they weren't, every delay is 2× too long.
- Measure the device's actual render rate during 1-1. If it ever drops below 30 fps, game time lags
  wall-clock time and `Project.time_scale` needs setting for that device.
- **Done when**: the conversion is documented in `runs.yaml`'s description or the methodology doc,
  and `task.yaml`'s `timing` section (§6.1) records the physics rate, the WAIT frame length, and the
  measured render rate.

### WP0.5 — Make the agent frame throttle configurable (small C++ change)

- Add `--agent-max-fps` (default 15, today's behavior). Training and latency measurement need
  30 fps when the host can sustain it, while the IDE is fine at 15.
- Also add `--agent-max-size` (plan §6's "raw frame" note) only if WP3.x shows 800 px is limiting.
  Don't build it speculatively.
- **Done when**: `--agent-max-fps 30` produces about 30 frames per second on the agent port under
  `--headless`, with no regression in the §13 lag fix.

### WP0.6 — Fix `DELAY`/`WAIT` drift in the executor

`GameRunExecutor._sleep_frames` and `LiveConnection.send_primitive`'s `WAIT` both use relative
`time.sleep`. Every send's own duration adds to the next delay, so a 20-node run accumulates drift.
Scheduling against the run's start time (`deadline = t0 + cumulative_ms`) removes the drift without
changing any file format. This matters for `level_1_1_clear`, where each jump's timing is
cumulative.

- **Done when**: a unit test with a fake connection that takes 5 ms per send shows the tenth
  action's actual start within ±5 ms of its scheduled time, versus ±50 ms or more today.

---

## 5. Phase 1 — Transport extraction (D10)

### WP1.1 — `irobot_client/` package

| Move | From | To | Compatibility |
|---|---|---|---|
| Wire encode/decode, constants | `tools/agent_client.py` | `irobot_client/protocol.py` | `agent_client.py` imports from it; its CLI is unchanged |
| `LiveConnection` | `irobot_gym_ide/connection.py` | `irobot_client/connection.py` | Old module re-exports; `_agent_client.py` shim deleted |
| — | — | `irobot_client/telemetry.py` | New (WP5.2) |

`agent_client.py` is run as a script from `tools/`, so it needs the repo root on `sys.path` to
import `irobot_client`. Add a two-line `sys.path` insert guarded by `__name__ == "__main__"`, or have
the `.cmd`/`.sh` launchers set `PYTHONPATH`. The launchers already `cd` to the repo root, so the
second option is the smaller change.

### WP1.2 — Protocol tests with byte fixtures

Per plan §11: capture real bytes for each message type (touch down/up/move, keycode, resolution
blob, screen-shot blob with phash, opencv-mat blob) from a live session, check them in as fixtures,
and assert encode/decode round-trips. This protects against wire drift if the C++ side changes.

### WP1.3 — Protocol version handshake

The length-prefix change was not versioned (plan §4.1 suggested it should be). An old unprefixed
client today is interpreted as a nonsense length and disconnected with a "frame too large" warning,
which is safe but confusing. Add a one-message handshake on connect: the client sends
`{"msg_type": "CONTROL_MSG_TYPE_HELLO", "protocol": 2}`, and the server logs the version and
rejects unknown major versions with a clear message. Old clients keep working, since the server
treats a missing hello as version 2 with a warning.

**Done when (phase)**: all existing tests pass unchanged, `agent_client.py stream/interactive`
still work, the IDE connects, and `irobot_client/tests` has fixture-based tests for every message
type.

---

## 6. Phase 2 — Task definition and signals (D5)

### 6.1 `task.yaml` schema

Lives in the IDE project directory. Loaded by `irobot_gym_ide.io.load_project` into a new
`Project.task` field (optional, so every existing project still loads). Example for
`mario_platformer`:

```yaml
schema_version: 1
id: ampere_run_1_1
description: "Ampere's Run, World 1-1: reach the flag without dying."

app:                                   # used by reset; package/activity also exist in project.yaml
  package: au.com.guidebee.supermorse  # super-morse's applicationId
  # MarioGameActivity is NOT exported (no intent filter), so `am start` can't open it directly.
  # Launch the exported launcher instead, and let a Game Run navigate (see reset.steps).
  launcher: com.guidebee.supermorse.activity.GamePickerActivity

timing:
  wait_frame_ms: 33                    # unit of existing `frames` fields (D9)
  game_physics_hz: 60                  # PHYSICS_FPS; per-render delta clamped to 1/30 s (§2)
  control_period_ms: 133               # D1; set from WP0.3 measurements
  step_timeout_ms: 1000

actions:
  tier: button                         # 0 | button (1.5); others are extension points
  source: gym_export                   # derive from hud.yaml + actions.yaml via gym_export
  macros: [long_jump]                  # which macro actions the codec exposes
  exclude: [fire]                      # e.g. hide fire until the fire power-up matters

observation:
  pixels: {size: [84, 84], channels: 1, source: opencv_mat}
  features:                            # optional; D3/D4
    source: telemetry                  # telemetry | vision | none
    fields: [player.x, player.y, player.vx, player.vy, player.grounded,
             enemies[0:3].dx, enemies[0:3].dy, terrain.gap_ahead_tiles,
             terrain.obstacle_ahead_tiles, terrain.obstacle_height_tiles]

signals:                               # registry name + params; evaluated every step
  progress:  {type: telemetry_field, field: progress.x}
  lives:     {type: telemetry_field, field: episode.lives}
  dead:      {type: telemetry_field, field: episode.dead}
  cleared:   {type: telemetry_field, field: episode.level_complete}
  stuck:     {type: phash_stuck, frames: 45}           # safety net (plan §8.4.4)
  # Vision-only fallbacks for a device build without telemetry:
  # progress: {type: scroll_progress, roi: [0, 0, 2670, 900]}
  # dead:     {type: template_match, template: game_over_banner}

reward:
  terms:
    - {signal: progress, kind: delta, scale: 0.01, clip: 1.0}   # like gym-super-mario-bros's x delta
    - {kind: per_step, value: -0.001}                           # mild time pressure
  terminal_penalty: -1.0
  success_bonus: 5.0

termination:
  terminated: [{signal: dead, when: "== true"}, {signal: cleared, when: "== true"}]
  truncated:  [{signal: stuck, when: "== true"}, {max_steps: 2000}]
  success:    [{signal: cleared, when: "== true"}]

reset:
  steps:
    - {adb: "am force-stop {package}"}
    - {adb: "am start -n {package}/{launcher}"}
    - {wait_stable_frames: 10, timeout_ms: 15000}
    - {run: open_level_1_1}            # a Game Run in runs.yaml: picker → Ampere's Run → level 1-1
    - {wait_signal: progress, timeout_ms: 5000}

safety:
  allowed_actions_only: true           # the codec never emits a touch outside declared regions
  max_episode_ms: 300000
```

Design notes:

- **`reset.steps` can call a Game Run.** Menu navigation is exactly what Game Runs are good at, and
  it's already authored in the IDE. That reuses the scripted driver inside the env instead of
  inventing a second menu-navigation mechanism.
- **Conditions are a tiny fixed grammar** (`== != < <= > >=` against a literal), not an expression
  language. That's the same reasoning `GAME_RUN_AI_ASSIST_DESIGN.md` §2.1.1 uses for the Condition
  node: structured fields validate statically and free-text formulas don't.
- **`success` is separate from `terminated`** because evaluation (§10) needs to distinguish "the
  episode ended because the level was cleared" from "the episode ended because the player died",
  and both are `terminated=True` to the RL algorithm.

### WP2.1 — Model and I/O

- `irobot_gym_ide/task.py`: dataclasses and `Task.validate(project)` returning warnings. It checks
  signal types exist in the registry, templates and Game Runs referenced exist, feature fields are
  well-formed, and macros named exist and are MACRO-kind. It uses the same "return warnings, never
  raise" convention as `GameRun.validate`.
- `io.py`: `TASK_FILENAME = "task.yaml"`, loaded if present.
- **Done when**: round-trip tests pass, including every field in §6.1, and validation tests cover
  every warning.

### WP2.2 — Signal registry and built-in signals

`irobot_gym/signals/`: a `Signal` base (`reset()`, `read(ctx) -> Reading`, with the reading a tagged
value or `Unavailable`, per plan §8.2) and a name→class registry. Ship in this order (cheapest and
most useful first, following plan §8.7 with two additions):

| Signal | Source | Notes |
|---|---|---|
| `telemetry_field` | Telemetry (WP5.2) | New. Rank-1 source (D4) |
| `phash_stuck` | Screen-shot phash | Plan §8.4.4; always `truncated`, never `terminated` |
| `template_match` | `ImageTemplate` | **Reuses `ImageTemplate.similarity`** from `model.py` instead of reimplementing (closes plan §14.3's duplication note) |
| `scroll_progress` | Consecutive frames | **New.** `cv2.phaseCorrelate` over a background ROI estimates horizontal camera motion. Summed, it's a dense, calibration-free progress signal for side-scrollers, the vision analogue of `x_pos`, which is the main reward term in `gym-super-mario-bros` |
| `icon_state` | ROI slots | Plan §8.3.6 |
| `health_bar` | ROI fill ratio | Plan §8.3 |
| `region_changed` | ROI phash | Plan §8.3.5 |
| `digit_template` | ROI + glyphs | Plan §8.3.3, with IDE-based glyph capture instead of a separate `calibrate_digits.py` |
| `logcat_regex` | `adb logcat` | Plan §8.3.1; generic regex version of `telemetry_field` |

- **Done when**: each signal has unit tests against recorded frames or recorded telemetry (no
  device), and the reset-artifact rule in plan §8.6 (score decreasing without a terminal event)
  has a test.

### WP2.3 — IDE panels (fill the stubs)

| Panel | Authors | Live preview |
|---|---|---|
| Observation | `observation.pixels`, `features` | Shows the canonical 84×84 frame and the current feature vector as the device plays |
| Reward | `signals`, `reward` | Draws signal ROIs on the canvas; shows each signal's live reading and the reward per step in a rolling chart |
| Reset | `reset.steps` | A "Test Reset" button runs the steps against the device and reports time taken and whether it reached a stable, playable state |

The live-preview-while-dragging behavior `irobot_gym_ide_design.md`'s Phase 2 section describes
belongs on the Reward panel's ROI tool.

- **Done when**: the `mario_platformer` project's `task.yaml` can be fully authored in the GUI,
  with an offscreen Qt smoke test covering load, edit, and save of each panel.

---

## 7. Phase 3 — `IrobotEnv`

### 7.1 API

```python
env = gymnasium.make(
    "irobot/Task-v0",
    project="irobot_gym_ide/examples/mario_platformer/project.yaml",
    backend="device",            # "device" | "sim"
    host=None, port=None,        # default: project.yaml's host/port
    render_mode=None,            # "rgb_array" returns the latest color thumbnail
    strict_timing=False,         # D1: repeat previous action on a missed slot
)
obs, info = env.reset(seed=None, options={"skip_app_restart": False})
obs, reward, terminated, truncated, info = env.step(action)
```

`reset(seed=...)` seeds only env-side randomness (for example random no-op starts). A real device
can't be seeded, and the docstring says so.

### 7.2 `info` keys (always present)

| Key | Meaning |
|---|---|
| `state` | Named structured state (D3/D4), the same dict Jev receives |
| `signals` | `{name: {"value", "delta"}}` for every signal, per plan §8.2.1 |
| `action_named` | The decoded, human-readable action applied this step |
| `obs_age_ms`, `step_ms`, `overrun_ms`, `missed_slots` | D1 timing |
| `action_latency_ms` | Input→effect latency when telemetry can measure it, otherwise absent |
| `success` | Only on the final step; from `termination.success` |
| `truncation_reason` | `stuck`, `max_steps`, `rotation`, `connection`, `timeout` |
| `health` | Per-cause relaunch counters (plan §9.1) |
| `inject_rejected` | Events rejected by `injectInputEvent` since last step (WP0.1's counter) |

### WP3.1 — Env skeleton over a fake backend

- `IrobotEnv`, `ActionCodec`, `ObservationBuilder`, fixed-rate stepping, `reset` interpreter for
  `reset.steps`.
- A `FakeBackend` that replays recorded frames and telemetry, used for all unit tests.
- `gymnasium.utils.env_checker.check_env` passes against `FakeBackend`. Note that its reset-seed
  determinism check will fail on a real device by construction, so it's run against fake and sim
  backends only, and the device backend has its own documented integration checklist (§11).
- **Done when**: `check_env` passes, and a test proves `terminated` and `truncated` are never
  swapped (plan §8.4 asks for exactly this test).

### WP3.2 — Device backend

- Wraps `irobot_client.LiveConnection`. Implements transition-only wire emission (plan §7.4:
  unchanged buttons send nothing).
- Releases every held pointer before reset (plan §7.1; `LiveConnection.release_all_held` already
  exists).
- **Done when**: 1,000 steps against a real device with a random policy produce no stalls, no
  leaked pointers (the backend's held-pointer set matches the codec's held state at every step, and
  is empty after `reset()`), and zero unexplained `inject_rejected`.

### WP3.3 — Health and relaunch (plan §9.1)

Implement as specified in plan §9.1: transport failure degrades to `truncated=True, reward=0` and
defers recovery to `reset()`, bounded retries (reconnect, then restart irobot, then raise
`TooManyRestartsError`), optional periodic restart, and per-cause counters.

- **Done when**: fault-injection tests (fake backend drops the socket mid-step; stops sending frames;
  returns a rotated resolution) each produce the specified degradation and recovery.

### WP3.4 — Registration and wrappers

- `gymnasium.register(id="irobot/Task-v0", entry_point=...)`.
- Wrappers: `ActionHistory(k)` (D1), frame stacking via Gymnasium's `FrameStackObservation`,
  `RecordEpisode` that writes the plan §13 "export episodes to replay format" output (an
  `events.json` that `agent_client.py play` can replay).

---

## 8. Phase 4 — TypeSafe Jev integration

This phase turns the `typesafe_agent/` prototype into a production driver and brings Jev into the
IDE. What's known about `typesafe-sdk` comes from `typesafe-mario/src/typesafe_mario/policy.py`:

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
client = TypeSafeClient()                     # reads TYPESAFE_API_KEY
response = client.system_one(state=<dict>, questions={
    "next_action": Choice(instructions=<dict|str>, criteria={name: description}),
    "jump_needed": Noul(instructions=<str>),                 # probability-like yes/no
    "danger":      Score(instructions=<str>, criteria=[low, mid, high]),
})
response.choices["next_action"].choice / .probabilities / .confidence
response.nouls["jump_needed"].noul
response.scores["danger"].score
```

Anything beyond this (rate limits, batching, pricing, latency distribution, determinism,
temperature) is **unknown** and listed in §13 as a question to resolve with TypeSafe before WP4.2's
defaults are fixed.

### 8.1 Jev state builders (`typesafe_agent/state/`)

One builder per D4 source. Each produces the same top-level shape, modeled on `typesafe-mario`'s
canonical state so prompts and lessons transfer. Fields a source can't provide are **omitted**, not
faked. The prompt is told which sections exist.

```jsonc
{
  "objective": "Reach the flag in World 1-1 without dying.",
  "source": "telemetry",                      // telemetry | vision | pixels
  "player": {"x": 412.5, "y": 96.0, "vx": 2.1, "vy": 0.0, "grounded": true,
             "jump_phase": "grounded", "power": "small"},
  "trajectory": {"airborne_ms": 0, "distance_since_takeoff": 0, "crossing_known_gap": false},
  "hazard": {                                   // computed in code, not by Jev
    "upcoming": [{"kind": "goomba", "dx": 88, "dy": 0, "vx_rel": -3.1,
                  "projected_dx_after_reaction": 41}],
    "contact_ms": 420, "takeoff_deadline_ms": 150,
    "jump_must_start_this_decision": true
  },
  "terrain": {"gap_ahead_tiles": null, "obstacle_ahead_tiles": 2, "obstacle_height_tiles": 2,
              "observation_reliability": "high"},
  "reaction_timing": {"control_period_ms": 133, "last_inference_ms": 610,
                      "total_reaction_horizon_ms": 743},
  "held": {"dpad": "right", "run_fire": "hold"},
  "recent_control": {"action": "right_run", "duration_ms": 1200, "progress_gained": 164,
                     "outcome": "advanced"},
  "episode": {"lives": 3, "progress": 412, "best_progress": 412, "stalled_ms": 0,
              "elapsed_ms": 8200}
}
```

- **Telemetry builder** (Ampere's Run): direct from telemetry fields, with `hazard` timing
  arithmetic ported from `typesafe-mario`'s `threat_features()`, converted to milliseconds and to
  Ampere's Run's own physics constants (from the methodology doc's constants file, D8).
- **Vision builder**: `player` from a player-marker template (or a fixed screen position for
  fixed-camera games, per `GAME_RUN_AI_ASSIST_DESIGN.md` §2.1.1), `hazard.upcoming` from
  multi-match template search against the project's enemy templates, `episode.progress` from
  `scroll_progress`. It sets `observation_reliability: "low"` so instructions can say not to trust
  fine timing.
- **Pixels builder**: today's prototype observation (frame changed, stalled time, held buttons).
  Kept as the floor.

**Held-state tracking** reads `HudRegion.action_name` and `release_action_name` pairs from
`hud.yaml` rather than the prototype's `*_start`/`*_stop` name-suffix convention, which the
prototype's own README flags as an assumption the schema doesn't guarantee. With the codec (D2), the
held state is simply the codec's current per-dimension value.

### 8.2 `JevPolicy` (WP4.1–4.2)

```python
class JevPolicy:
    def __init__(self, task, codec, *, instructions: JevInstructions,
                 timeout_ms=2500, fallback="hold", budget=JevBudget(...)): ...
    def request(self, state: dict) -> Future[Decision]: ...   # non-blocking
    def close(self): ...
```

- **Action vocabulary for Jev = codec *named* combinations, not raw project actions.** The
  prototype offers all 13 project actions (including `up_stop` and `down_start`), which invites
  meaningless choices. Jev instead chooses among a curated macro set declared in the task's
  `agent.jev.actions`, mirroring `typesafe-mario`'s seven macros. Each has a description; for
  Ampere's Run: `noop`, `right`, `right_run`, `right_jump`, `right_run_jump`, `jump`, `left`,
  `long_jump`. The codec maps each to a `MultiDiscrete` value (or macro).
- **Question set**: `Choice` (next macro), `Noul` (whether a forward jump is needed now), `Score`
  (immediate danger), the same three `typesafe-mario` uses. `Noul` and `Score` aren't used for
  control. They're logged and shown in the dashboard, and they give evaluation a free check of
  whether Jev's reasoning is consistent with its choice.
- **Jump edge handling**: Ampere's Run's `jumpPressed` is edge-triggered (`PlatformerCommand`
  javadoc). If Jev picks a jump macro while the jump pointer is already down, the codec releases it
  for one control period first. That's `typesafe-mario`'s `JUMP_RELEASE_ACTION`, moved into the
  codec so every driver gets it.
- **Instructions are versioned data**, not code: `task.yaml`'s `agent.jev.instructions` (or a
  sibling `jev_instructions.yaml`), hashed into every decision log record so a behavior change can be
  traced to a prompt change.
- **Budget**: `max_decisions_per_episode`, `max_decisions_per_hour`, `max_consecutive_errors`. On
  exhaustion the policy switches to its fallback and records why.
- **Secrets**: `TYPESAFE_API_KEY` comes only from the environment. It is never written to
  `project.yaml`, logs, or decision records. The decision log is written with the state and
  answers, which contain no screen pixels. Screens never leave the machine because Jev doesn't
  receive them (§1.3), which is worth stating to anyone reviewing data handling.

### 8.3 WP4.3 — `typesafe_agent` becomes a driver over `IrobotEnv`

- `runner.py` is replaced by a loop that uses `irobot_gym`'s `AsyncPolicyRunner` (D1) around
  `JevPolicy`. It keeps its CLI (`state-demo`, `latency-check`, `play`) and adds `--backend sim`.
- `latency-check` gains the telemetry-echo mode (WP0.3).
- The decision log format (§8.5) replaces the prototype's ad-hoc JSONL.
- The prototype's two flaws noted in its README (blocking loop; suffix-based hold bookkeeping) are
  removed by construction.
- **Done when**: `typesafe_agent play --backend sim` completes World 1-1 in simulation at least
  once, and `--backend device` runs 500 decisions without an unhandled exception, with the
  decision log validating against its schema.

### 8.4 WP4.4 — IDE "Agent" tab

A fourth tab next to Define, Sessions, and Game Run:

- **Live view**: the canvas with an overlay of the named action currently held, and markers for the
  entities in `state.hazard.upcoming` (from telemetry or vision).
- **Decision stream**: one row per decision with the chosen action, a probability bar across all
  macros, confidence, `Noul` and `Score` values, and latency. Clicking a row shows the full state
  JSON sent to Jev.
- **Controls**: Start/Stop, policy picker (Jev / Heuristic / a loaded SB3 checkpoint), a budget
  display, and **Take Over**: a human override that suspends the policy while the human plays
  through the canvas (existing click-to-send path). Takeovers are logged as human decisions, so the
  log doubles as a demonstration dataset (plan §13's imitation-learning warm start).
- **Save as Game Run**: runs the trace compiler (§8.6) on the current or selected trace and opens
  the result in the Game Run tab for review. It's never saved without that review, per
  `GAME_RUN_AI_ASSIST_DESIGN.md` §3.1 step 3.

This is a deliberate scope change for the IDE. `irobot_gym_ide_design.md` §1 says "which AI agent
later plays the game is entirely out of scope". The IDE still doesn't *train* anything. Supervising
and inspecting an agent against the same live canvas, templates, and regions the IDE already owns
is a natural extension, and building it anywhere else would duplicate the canvas.

### 8.5 Decision log record (schema)

```jsonc
{
  "schema": "irobot.decision/1",
  "run_id": "2026-10-03T101512Z-ampere-1-1",
  "decision_index": 41,
  "driver": "jev",                         // jev | heuristic | sb3 | human | replay
  "t_request_ms": 5471, "t_answer_ms": 6082, "t_applied_ms": 6133,
  "control_step_at_request": 41, "control_step_at_apply": 46,
  "state": { /* §8.1 */ },
  "instructions_sha256": "…",
  "answer": {"choice": "right_run_jump", "confidence": 0.81,
             "probabilities": {"right_run_jump": 0.81, "right_jump": 0.11, "…": 0.08},
             "jump_needed": 0.93, "danger": 0.72},
  "fallback": null,                        // or {"reason": "timeout|error|budget|invalid"}
  "applied": {"dpad": "right", "jump": "tap", "run_fire": "hold"},
  "outcome_next": {"progress_gained": 38, "died": false}
}
```

`control_step_at_apply - control_step_at_request` is the delay, in control steps, between when
Jev saw the state and when its answer took effect. It's the quantity D1 is about, and it's the
first thing to look at when Jev "reacts late".

### 8.6 WP4.5 — Trace→Game Run compiler (`typesafe_agent/trace.py`)

Input: a decision log (optionally trimmed to a range). Output: a `GameRun` dict.

1. Walk records in `t_applied_ms` order. Convert each change in `applied` (per codec dimension) into
   the corresponding project actions, for example `dpad: none→right` becomes `right_start` and
   `jump: none→tap` becomes `jump`.
2. Between consecutive changes, emit a `DELAY` node of `round(Δt_ms / wait_frame_ms)` WAIT frames,
   using a cumulative accumulator (the same fix as `device_recorder._insert_wait_gaps`, so rounding
   doesn't discard time).
3. Concurrent changes in one record become one fork with a join (Game Run fork/join semantics).
4. Close with stop actions for every still-held dimension.
5. Run `GameRun.validate()` and `run_pointer_conflicts()` and attach any warnings.
6. Optionally insert `ASSERT` nodes at points where the trace recorded a known-good state (for
   example, a checkpoint template the vision builder matched), so the compiled run is
   regression-testable.

- **Done when**: compiling a trace from a successful sim run and replaying the compiled Game Run in
  sim reproduces the same outcome, and a unit test covers accumulator rounding and fork/join
  emission.

### 8.7 WP4.6 — `DECIDE` node (D7)

Schema addition to `RunNodeKind`:

```yaml
- id: n_route
  kind: decide
  question: "Take the upper route or the lower route?"
  options: [upper, lower]            # each option is an outgoing edge's `via` label
  state_source: telemetry            # telemetry | vision | variables
  timeout_ms: 3000
  fallback: lower                    # edge taken on timeout/error/budget
  mode: live_or_replay               # live | replay | live_or_replay
```

- `run_engine.py` gains `_run_decide`. It builds state, calls `JevPolicy`-style `Choice` with
  `options` as criteria, records to `<project>/decisions/<run>.decisions.jsonl` keyed by
  `(node_id, visit_index)`, and returns the chosen `via`.
- `GameRun.validate()`: every option must have exactly one outgoing edge with that `via`, the
  fallback must be one of the options, and a `decide` node inside a `REPEAT` body gets a warning that
  replay keys by visit index.
- `dry_run.DryRunConnection`: in dry run, a `decide` node takes its recorded decision if one exists,
  else its fallback, and logs which.
- The executor never blocks the whole graph: other forked branches keep running while a `decide`
  waits (the fork/join model already runs branches on separate threads).
- **Done when**: tests cover live (with a fake Jev client), replay (with no Jev client installed at
  all), timeout→fallback, and validation warnings.

### 8.8 WP4.7 — Jev as a design-time assistant (optional, after 4.1–4.6)

`GAME_RUN_AI_ASSIST_DESIGN.md` §3.4 proposes a `design_action_sequence` MCP tool. That tool needs a
vision-capable model for terrain reasoning, which Jev isn't. Jev fits two adjacent roles instead:

- **Choosing among generated candidates**: the methodology doc's scheduler (or a vision model) proposes
  several candidate schedules. Jev ranks them with a `Choice` over structured summaries (hazards
  covered, margin per hazard, total time). That's a judgment task over typed facts, which is what
  Jev is for.
- **Outcome judgment as an assertion**: an `ASSERT`-like check where a `Noul` over telemetry state
  answers questions a template can't ("did the player end this maneuver standing on the upper
  platform?"). Keep this out of reward (it's slow and costs money per call). Use it for evaluation
  and regression reports.

---

## 9. Phase 5 — Ampere's Run telemetry and simulator (D4, D8)

This phase changes `guidebee/super-morse` (a separate repository), so it needs its own branch and
review there.

### WP5.1 — Debug telemetry emitter in super-morse

- Location: `app/src/main/java/com/guidebee/supermorse/platformer/debug/AgentTelemetry.java`, next
  to the existing `LevelWarpPanel.java` in the same `debug` package.
- **Compiled into debug builds only** (a `BuildConfig.DEBUG` guard at the call site, plus R8 removal
  in release). Release APKs contain no emitter.
- Emits one line every *N* rendered frames (default N = 4, so about 15 Hz at 60 fps) via
  `Log.i("AmpereTelemetry", json)`:

```json
{"v":1,"rf":1843,"gt_ms":30712,"t":123456789,
 "p":{"x":412.5,"y":96.0,"vx":2.1,"vy":0.0,"g":1,"pw":"small"},
 "e":[{"k":"goomba","x":500.0,"y":96.0,"vx":-1.0}],
 "tr":{"gap":null,"obs":2,"obsh":2},
 "cmd":{"l":0,"r":1,"jp":0,"jh":0,"run":1},
 "ep":{"lives":3,"coins":4,"prog":412.5,"dead":0,"done":0,"lvl":"1-1"}}
```

- `rf` is the render-frame counter and `gt_ms` is accumulated, clamped game time (§2, D9). When
  `gt_ms` advances more slowly than `t`, the device is rendering below 30 fps.
- `cmd` is the `PlatformerCommand` the game actually read that frame. Comparing `cmd` edges against
  the host's send times gives true input→game latency (WP0.3), which pixels can't. Since the
  emitter only writes every *N* frames, it also latches any `jp`/`jh` edge seen since the last line
  so a one-frame jump press isn't missed.
- **Optional fast-reset hook**, also debug-only: let the exported `GamePickerActivity` accept an
  intent extra (for example `--es agent_level 1-1`) that opens Ampere's Run directly at a level.
  That turns reset from a menu-navigating Game Run (seconds) into one `am start` call. It's a
  launch convenience, not a control path, so it doesn't conflict with D4's observation-only rule
  for gameplay.
- Fields come from existing classes (`MarioWorld`, `PowerStateActor`, `TileWorld`,
  `LevelProgressState`, `ScoreLivesState`, `PlatformerCommand`). Nothing new is computed in the game
  beyond a short forward scan of the tile map for `tr`.
- Cost: one small string build and a logcat write at 15 Hz. Measure frame time with and without it,
  and don't ship if it costs more than 0.5 ms per rendered frame.
- **Done when**: `adb logcat -v raw -s AmpereTelemetry:I` shows well-formed lines during play,
  and a debug-vs-release APK diff confirms the emitter isn't present in release.

### WP5.2 — `TelemetryTail` (`irobot_client/telemetry.py`)

- Spawns `adb -s <serial> logcat -v epoch -s AmpereTelemetry:I` (tag configurable), parses lines on
  a background thread, and keeps the latest record plus a short ring buffer, following the same
  latest-value-under-a-lock pattern `LiveConnection` uses for frames.
- Reports `telemetry_age_ms`. The env treats telemetry older than `2 × control_period_ms` as
  `Unavailable` rather than stale truth.
- Clears the logcat buffer on reset (`logcat -c`) so a new episode never reads the previous one's
  last lines.

### WP5.3 — Simulator backend

- Build on `game_run_design_methodology.md` §7 items 1–2 (level compiler, physics constants file).
- Implements the backend interface: `apply(named_action)`, `advance(ms)`, `observe() -> (pixels,
  telemetry_record)`. Telemetry records in the same schema as WP5.1 mean the same state builders,
  signals, and features work unchanged.
- Enemy behavior must include wall/ledge turn-around, which the methodology doc's §6 lists as a
  known gap in its current simulation.
- Physics must reproduce the game's variable-timestep behavior, including the 1/30 s delta clamp,
  so the sim can be run at the device's measured render rate, not only at an idealized 60 fps.
- Latency randomization (D8), drawn from WP0.3's measured distribution.
- **Fidelity test**: record telemetry and the host-side action log from a device run, replay the
  same actions in sim at the same times, and compare player x/y at matching `gt_ms`. Target: under
  0.5 tile mean absolute error over the first 30 seconds of 1-1. Run in CI against the checked-in
  recording.
- **Done when**: the fidelity test passes, and the sim runs at least 2,000 env steps per second on a
  laptop CPU in feature-only mode.

---

## 10. Phase 6 — RL baseline and evaluation

### WP6.1 — PPO in simulation

- SB3 `PPO` with `MultiInputPolicy` (pixels plus features) or `MlpPolicy` (features only), on
  `SimBackend`, `MultiDiscrete` actions (D2), `ActionHistory(4)`, latency randomization on.
- **Done when**: at least 80% level-clear rate on 1-1 in sim over 100 evaluation episodes.

### WP6.2 — Transfer to device

- Evaluate the sim-trained policy on the device with no fine-tuning, then fine-tune briefly on the
  device if needed.
- Behavior cloning warm start from two free sources: compiled scripted runs (`level_1_1_clear`) and
  Jev traces with human takeovers (§8.4).

### WP6.3 — Evaluation harness (`eval/`)

One command runs each driver on the same task for *N* episodes and writes a report:

| Metric | Why |
|---|---|
| Level-clear rate | The headline outcome |
| Mean and max progress | Partial credit, comparable across drivers |
| Time to clear (successful episodes) | Efficiency |
| Deaths by cause (enemy, gap, timeout) | Where each driver fails |
| Decision latency p50/p95 (Jev) | D1/D6 health |
| Fallback rate and reasons (Jev) | Whether the budget, timeout, and prompt are right |
| Cost per episode (Jev) | Once TypeSafe pricing is known (§13) |
| `missed_slots`, `inject_rejected`, relaunches | Infrastructure health, so a bad score isn't blamed on the policy |

Drivers compared: **scripted** (`level_1_1_clear`), **heuristic**, **Jev (telemetry state)**,
**Jev (vision state)**, **Jev (pixels state)**, **PPO**. The three Jev variants isolate how much
state quality matters, which is the D4 hypothesis this plan rests on. If Jev with vision state is
close to Jev with telemetry state, D4's rank-1 source matters less than expected for unowned games,
and that's worth knowing.

Real-device episodes are expensive and non-reproducible, so the harness also records each device
episode's full decision log and telemetry. Rerunning an analysis never requires rerunning the
device.

---

## 11. Testing strategy

| Layer | Test type | Needs device? |
|---|---|---|
| `irobot_client.protocol` | Byte-fixture round trips | No |
| `irobot_client.connection` | Fake TCP server (the pattern `irobot_gym_ide_design.md` §6.1 already uses) | No |
| `irobot_client.telemetry` | Fake `adb` process emitting recorded lines (the pattern `device_recorder` tests already use) | No |
| `task.py`, signals, codec | Unit tests on recorded frames and telemetry | No |
| `IrobotEnv` | `check_env` on fake and sim backends; fault injection; terminated/truncated swap test | No |
| Jev policy | Fake `TypeSafeClient` (timeouts, errors, invalid choices, slow answers) | No |
| `DECIDE` node, trace compiler | Unit tests plus sim round trip | No |
| Sim fidelity | Recorded device trajectory vs sim | No (recording checked in) |
| Device integration | Manual checklist below, recorded in `docs/measurements/` | Yes |

**Device integration checklist** (before any phase is called done on device):

1. 10 consecutive replays of `level1.session.yaml` have a visible effect (WP0.1).
2. 1,000 random-policy steps: no stall, no leaked pointer, `inject_rejected == 0`.
3. One full episode ending `terminated=True` via a real death, one via a level clear.
4. One episode where the socket is killed mid-run: `truncated=True`, then a successful `reset()`.
5. Two parallel envs against two devices or emulators (plan §10).

---

## 12. Schedule and dependencies

Estimates are in engineer-days for one person familiar with the codebase, and assume WP0.1 doesn't
turn out to be an Android framework limitation. If it does, re-plan.

| WP | Title | Depends on | Estimate |
|---|---|---|---|
| 0.1 | Silent touch-drop root cause | — | 2–5 |
| 0.2 | Doc hygiene | — | 1 |
| 0.3 | Latency measurement | 0.1 | 1–2 |
| 0.4 | Frame-unit reconciliation | — | 0.5 |
| 0.5 | `--agent-max-fps` | — | 1 |
| 0.6 | Drift-free delays | — | 1 |
| 1.1–1.3 | `irobot_client` extraction, fixtures, handshake | 0.1 | 3–4 |
| 2.1 | `task.yaml` model/io | 1.1 | 2 |
| 2.2 | Signals | 2.1 | 5–7 |
| 2.3 | IDE panels | 2.1, 2.2 | 5–8 |
| 3.1–3.4 | `IrobotEnv` | 1.x, 2.1–2.2 | 8–10 |
| 5.1 | Telemetry emitter (super-morse) | 0.4 | 2 |
| 5.2 | `TelemetryTail` | 1.1, 5.1 | 1–2 |
| 4.1–4.3 | Jev state builders, `JevPolicy`, driver rewrite | 3.1, 5.2 | 6–8 |
| 4.4 | IDE Agent tab | 4.3 | 5–7 |
| 4.5 | Trace compiler | 4.3 | 2–3 |
| 4.6 | `DECIDE` node | 4.2 | 3–4 |
| 5.3 | Simulator + fidelity test | 5.1, 5.2 | 8–12 |
| 6.1–6.3 | PPO, transfer, eval harness | 3.x, 5.3 | 8–12 |
| 4.7 | Jev design-time assist | 4.x | optional |

**Critical path**: 0.1 → 1.1 → 2.1 → 3.1 → 4.3 → 6.3. Telemetry (5.1–5.2) can proceed in parallel
with Phases 1–2, since it's a separate repository. The simulator (5.3) is the largest single item
and the one to cut first if time is short: Jev on device doesn't need it, only RL at scale does.

**Milestones**:

| Milestone | Contents | Demonstrates |
|---|---|---|
| M0 "Trustworthy pipe" | Phase 0 | Device does what it's told; latency is a known number |
| M1 "Env on device" | Phases 1–3 | `check_env` passes; random policy runs 1,000 steps on device |
| M2 "Jev plays" | 5.1–5.2, 4.1–4.4 | Jev with telemetry state plays 1-1 on device; decisions visible in IDE |
| M3 "Jev authors" | 4.5–4.6 | A Jev playthrough compiled into a reviewed, replayable Game Run |
| M4 "Scale" | 5.3, Phase 6 | PPO trained in sim, evaluated on device; driver comparison report |

---

## 13. Risks and open questions

### 13.1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WP0.1's root cause is in Android's input dispatcher, not irobot | Medium | High: every driver is blocked | Time-box to 5 days; escalate with the rejected-event counter's data; test another device and Android version |
| Jev latency (unknown) exceeds platformer reaction windows | High | Medium | D1/D6 async design; code computes deadline facts; `DECIDE` only at strategic points; compare Jev-telemetry vs heuristic in the eval to quantify |
| Sim–device gap makes sim-trained PPO useless on device | Medium | Medium | Fidelity test in CI; latency randomization; BC warm start; fine-tune on device |
| Telemetry emitter changes game timing | Low | Medium | Measure frame time; 0.5 ms budget; debug-only |
| Logcat adds variable delay to telemetry | Medium | Low | `telemetry_age_ms` gating; if logcat proves too slow, switch the emitter to a local socket read over `adb forward`, with the same JSON schema |
| Scope creep in the IDE (Agent tab, panels) delays the env | Medium | Medium | The env (Phase 3) doesn't depend on any GUI work; the panels can land after M1 |
| API cost of Jev during long runs | Unknown | Unknown | Budgets (§8.2); record and replay; sim-first prompt iteration |

### 13.2 Questions to resolve with TypeSafe before WP4.2

1. Latency distribution for `system_one` with three questions and a ~2 KB state: p50 and p95?
2. Rate limits and concurrency limits per key?
3. Pricing per request, and whether the three questions count as one request or three.
4. Is there a determinism or temperature control? It affects whether replay of recorded decisions is
   needed (it always is for D7) or whether re-asking would reproduce an answer.
5. Can a request be cancelled, so a timed-out request doesn't keep costing money?
6. Data retention for submitted state (relevant only if a state ever contains user data; today it's
   game physics only).

### 13.3 Questions for the project owner

1. **Confirm the super-morse change** (WP5.1). It's debug-only and observation-only, but it's a
   change to a second repository.
2. **Priority between M2 (Jev plays) and M4 (PPO scale).** This plan puts Jev first because the
   prototype exists and the value is quicker to show. If RL is the real goal, 5.3 moves earlier.
3. **Real device, emulator, or both for CI-adjacent device checks?** An emulator makes snapshot
   resets (plan §13) and unattended runs possible. A real device is what irobot exists to support.
4. **Where should decision logs and eval reports live?** In-repo `artifacts/` (gitignored) is the
   default. A shared location would let the team compare runs.
