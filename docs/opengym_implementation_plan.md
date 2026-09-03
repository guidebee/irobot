# OpenAI Gym / Gymnasium Environment — Implementation Plan

Status: design document, not yet implemented. Companion to the [README roadmap](../README.md#roadmap) and
[tools/README.md roadmap](../tools/README.md#roadmap). Written to let any future contributor (human or agent)
pick this up without re-deriving the protocol analysis below.

## 1. Goal

Wrap the existing AgentManager sockets (`--port`+1 control, `--port`+2 video) in a standard
`gymnasium.Env` (`reset()` / `step(action) -> (obs, reward, terminated, truncated, info)`) so
Stable-Baselines3 / RLlib / CleanRL can train against Android games with no irobot-side glue beyond
what already exists. `tools/agent_client.py` remains the manual/reference layer; the Gym env is a new,
separate Python package that reuses its wire-protocol code rather than duplicating it.

### 1.1 Feasibility assessment: real-time shooting/fighting games specifically

**Verdict: feasible as a research/training platform for a real, meaningful slice of real-time games —
but "plays well" is genre-dependent, and this is a reason to validate the riskiest assumption early,
not a reason not to build it.** Of the two genres named, bullet-hell-style shooting and frame-perfect
PC/console-style fighting sit closest to this architecture's actual limits; mobile-native
fighting/shooting games with second-scale (not frame-scale) reaction windows sit comfortably within
it. The five points below are why, most-important first.

1. **Control-loop latency is the dominant risk — not algorithm choice, not reward design.** Trace the
   actual round trip one action takes: device screen change → on-device H.264 encode → ADB/socket
   tunnel → irobot decode → `ConvertToMat`+`computePHash` → TCP to the agent video port → Python read →
   policy inference → JSON encode → TCP to the agent control port → `AgentController` → forward to the
   device control socket → Android input dispatch → game engine processes the touch → renders the
   *next* frame the agent will see. scrcpy's own published figure for the video-mirroring leg **alone**
   (device change → visible on desktop, USB, nothing else in the path) is **~35–70ms best case**
   ([scrcpy README/manpage](https://manpages.debian.org/testing/scrcpy/scrcpy.1.en.html)). irobot's
   agent path — which this project is built on — adds a full second leg on top of that (another
   decode/re-encode, two more TCP hops each direction, plus inference cost) before an action's *effect*
   is visible back to the agent. **Nobody has measured this number for the agent path yet — that's the
   point.** A reasoned estimate is 100–300ms round-trip; for a genre with sub-100ms reaction/parry
   windows, that budget may simply not exist, independent of training quality — an architectural
   ceiling, not something more environment steps fixes. **Recommendation: build a minimal latency
   benchmark (send a touch, count frames until a known on-screen element visibly responds) as the very
   first validation step — before §8's reward/adapter machinery — since it tells you which genres are
   realistically in reach before further investment.**
2. **Observation fidelity for small/fast objects.** The default observation (§6) is grayscale, ≤800px
   long side, sourced from an **H.264-compressed** frame. Bullet-hell shooting lives entirely in
   tracking small, fast-moving projectiles — exactly the content lossy compression and downscaling
   degrade first, and exactly what §13's throughput-tuning idea (lower bitrate for speed) cuts against.
   Confirm bullets/projectiles are still visually distinguishable at training-time resolution/bitrate
   before committing to that genre; if not, §6's not-built "raw/undownscaled frame" option stops being
   a nice-to-have and becomes a prerequisite for it specifically.
3. **Training sample efficiency vs. real-world step throughput.** Real-time action games are the
   well-known hard end of RL sample efficiency — the literal reason Atari/StarCraft/Dota-scale agents
   needed enormous compute; 10M+ environment steps is a common floor. Every step here costs a real
   device round trip (point 1), so throughput is likely single-to-low-double-digit steps/second per
   instance — and unlike Atari's free CPU-simulated parallelism, each parallel instance needs its own
   physical device or emulator (§10's real bottleneck, not the socket protocol). Size this out
   concretely (steps/sec × instance count × wall-clock budget) for the specific game's difficulty
   before assuming "plays well" is reachable in a given timeframe.
4. **Live/PvP multiplayer is a different risk category entirely.** If the target is a live-service
   game with real-opponent matchmaking: most such games run server-side anti-cheat/bot-detection that
   specifically looks for the input-timing signatures a scripted, socket-driven agent produces —
   training risks the account being banned mid-run, on top of the RL problem's own non-stationary-
   opponent difficulty. Strongly prefer single-player campaign, offline, or practice/VS-AI modes —
   both for a stable, resettable environment (§9's `reset_episode()` already assumes one) and to avoid
   ToS/account risk entirely.
5. **Where this is genuinely well-suited.** Mobile-native fighting games (as opposed to console/PC
   fighters ported over) are usually designed around touchscreen input — simplified combos, generous
   input-buffer windows, on-screen buttons that map cleanly onto §7's per-game `ActionMap`. Real-time
   games with second-scale reaction windows sit comfortably inside even a pessimistic 100–300ms
   latency budget. And HP-bar-style reward is an easy case for §8's tiered design: reading a health bar
   ROI's fill ratio (crop + color threshold + pixel count — no OCR/digit-matching needed) is cheap,
   robust, and a natural continuous reward signal for exactly the genres named here — see the
   `HealthBarFillRatioSignal` note added to §8.3/§8.7.

## 2. What exists today (verified against source, not assumed)

| Piece | Where | Notes |
|---|---|---|
| Control socket (agent → irobot) | `src/agent/agent_controller.cpp` `ProcessMessages` | JSON `ControlMessage`, see framing gap below |
| Video socket (irobot → agent) | `src/agent/agent_stream.cpp`, `AgentManager::SendOpenCVImage` | Binary `BlobMessage`, push-only, unsolicited |
| Frame conversion | `src/ai/brain.cpp` `ConvertToMat` | Two variants pushed per source frame: `BLOB_MSG_TYPE_OPENCV_MAT` (≤800px, grayscale) and `BLOB_MSG_TYPE_SCREEN_SHOT` (≤240px, color) |
| Perceptual hash | `computePHash` in `agent_manager.cpp` | 8-byte DCT hash appended as a second buffer in the same `BlobMessage` |
| Reference client | `tools/agent_client.py` | `record`/`play`/`stream`/`interactive`; has working encode/decode for both channels |
| Event recording | Ctrl+E in `irobot.exe` → `events.json` | `ControlMessage::JsonSerialize`, replayable by `agent_client.py play` |

## 3. Protocol facts that constrain the design (read before writing code)

These are not roadmap opinions — they were confirmed by reading `control_msg.cpp` /
`agent_controller.cpp` directly, and they directly shape Phase 0 below:

1. **`AgentController::ProcessMessages` framing is whole-buffer, not incremental.**
   `ControlMessage::JsonDeserialize` calls `nlohmann::json::accept()` on the *entire* unconsumed
   buffer (`control_msg.cpp:315`). If that succeeds it consumes the whole buffer (`ret = len`) and
   parses one message. If it fails — including the case where the buffer contains **two valid,
   complete JSON objects concatenated** (a near-certainty once a training loop is issuing several
   actions per second and TCP coalesces writes) — it returns `0`, which `AgentController::ProcessMessages`
   (`agent_controller.cpp:110`) treats as "wait for more bytes." But more bytes never fixes a
   multi-document buffer; it can only grow until it hits `CONTROL_MSG_SERIALIZED_MAX_SIZE * 2`, at
   which point the assert/overflow path is hit. **This is a real stall/crash risk at RL step rates,
   not a theoretical one.** `agent_client.py`'s "one JSON object per `send()`" discipline works around
   it today by relying on the client never issuing back-to-back writes fast enough to coalesce — a
   training loop will not have that luxury.
2. **The video channel is push-only and unsolicited.** `AgentManager::SendOpenCVImage` fires off the
   SDL event loop (`EVENT_NEW_OPENCV_FRAME`), not in response to a client request. A `step()` cannot
   "ask for the next frame" — it must consume whatever the background reader thread most recently
   buffered. Frame arrival rate is decoupled from action rate.
3. **`screen_size` for touch events must equal the real negotiated video resolution exactly**
   (`Size.equals()`, no tolerance) — see `tools/README.md#why---screen-size`. Today this is a
   `--screen-size` argument the human supplies by reading irobot's stdout (`Initial texture: WxH`).
   Nothing on either socket currently reports this value programmatically. A Gym env cannot ask a
   human to read stdout, so this has to be solved before `step()`/`reset()` can be fully automated
   (Phase 0).
4. Video port and control port are independent TCP connections with independent accept loops
   (`AgentManager::Init`); reconnecting one does not affect the other.

## 4. Phase 0 — C++ protocol hardening (prerequisite, small and additive)

Both changes are additive (no existing message shapes change), so `agent_client.py` and any other
existing consumer keep working unmodified.

1. **Length-prefixed control framing.** Prepend a 4-byte big-endian length to each JSON control
   message on the wire, and change `AgentController::ProcessMessages` to read exactly that many bytes
   before calling `JsonDeserialize`, instead of feeding it the whole unconsumed buffer. This is the
   direct fix for the stall risk in §3.1. Bump a protocol version so `agent_client.py` (old framing)
   and any future length-prefixed clients don't get silently misread — simplest: a new listen port or
   a 1-byte protocol flag in the existing connect handshake; decide in implementation, not here.
2. **Resolution announcement.** Add a new `BlobMessageType` (e.g. `BLOB_MSG_TYPE_RESOLUTION`) sent once
   right after `AgentStream` accepts a client connection, and again whenever `src/ui/screen.cpp`'s
   "New texture" rotation path fires — same trigger point as the existing stdout log line. Payload:
   just `width`/`height` (reuse the existing buffer `[width:u64][height:u64]` framing already used for
   image buffers, with a zero-length pixel payload). This removes the manual `--screen-size` step
   entirely and lets the env recover automatically from an in-episode rotation instead of silently
   dropping every touch event afterward.

Everything past this point (Phases 1+) is pure Python and does not require another C++ change,
*except* Phase 6's optional headless/no-window mode consideration (§9).

## 5. Package layout

New package, not mixed into `tools/agent_client.py`: `tools/irobot_gym/`.

```text
tools/irobot_gym/
├── protocol.py            # wire encode/decode, refactored OUT of agent_client.py (both import this)
├── connection.py          # socket lifecycle: connect, background frame-reader thread, reconnect
├── env.py                 # IrobotEnv(gymnasium.Env) — owns reward composition (§8.5), see GameAdapter
├── spaces.py               # action-space tiers 0/0.1/1/2 (§7.3) + ActionMap per-game config loader
├── adapters/
│   ├── base.py             # ScoreSignal / TerminalSignal / GameAdapter ABCs (§8.2)
│   ├── score/
│   │   ├── region_changed.py   # RegionChangedScoreSignal (§8.3.5) -- v1 default
│   │   ├── digit_template.py   # DigitTemplateScoreSignal (§8.3.3) -- v1
│   │   └── tesseract_ocr.py    # TesseractScoreSignal (§8.3.4) -- documented extension point, not v1
│   └── terminal/
│       ├── phash_stuck.py      # PHashStuckTerminalSignal (§8.4.4) -- v1
│       └── template_match.py   # TemplateMatchTerminalSignal (§8.4.3) -- v1
├── calibrate_digits.py     # one-time per-game tool: click-crop digit glyphs 0-9 from a paused frame
├── launcher.py             # spawns N `irobot` subprocesses (distinct --serial/--port) for VecEnv use
├── examples/
│   ├── logcat_reward_recipe.md  # how to find/wire a LogcatScoreSignal/LogcatTerminalSignal (§8.3.1/§8.4.1)
│   └── train_ppo.py             # Stable-Baselines3 smoke-test script
└── tests/
    ├── test_protocol.py    # encode/decode against fixed byte fixtures, no device/socket needed
    └── test_env_checker.py # gymnasium.utils.env_checker.check_env against a mocked connection
```

`agent_client.py` gets refactored to import `protocol.py` for its message encode/decode instead of
inlining it, so the wire format has exactly one implementation. This is the only change to existing
files in this plan — everything else is additive.

## 6. Observation space

- Default: `Box(low=0, high=255, shape=(H, W, 1), dtype=uint8)` from `BLOB_MSG_TYPE_OPENCV_MAT`
  (grayscale, ≤800px long side). Channel-last (`H, W, C`) to match SB3's default `CnnPolicy` /
  `VecTransposeImage` expectations.
- Optional `obs_mode="color"`: use `BLOB_MSG_TYPE_SCREEN_SHOT` instead — smaller (≤240px), color,
  `shape=(H, W, 3)`.
- Optional `obs_mode="raw"`: request the undownscaled frame. **Not available today** — both blob types
  are always downscaled server-side (`AgentManager::HandleEvent` hardcodes `800`/`240` as `max_size` in
  `SendOpenCVImage` calls). Adding a raw/undownscaled option means either a new call with
  `max_size=0`/sentinel meaning "native," or exposing `max_size` as a CLI/runtime-configurable value.
  Flag as a small Phase-0-adjacent C++ change if/when an agent actually needs it — don't build it
  speculatively.
- Audio: intentionally **not** in the observation space for v1, matching the README roadmap's
  reasoning (no genre-agnostic justification for the wire/perf cost). Leave a documented extension
  point in `env.py` (`include_audio: bool = False`) rather than plumbing it through now.
- Frame staleness: because the video channel is push-only (§3.2), `connection.py`'s reader thread must
  track "is this the newest frame since the last `step()`'s action was sent" — expose an
  `info["frame_age_steps"]` or similar so training code can detect a stalled stream instead of
  silently training on repeated stale frames.
- **Motion info (velocity/direction) and object/vector-shape extraction are explicitly out of scope
  for the env itself.** Considered and deliberately dropped: converting raster frames to vector
  shapes (contour extraction + cross-frame object tracking for per-shape speed/direction) only
  generalizes to a narrow class of games (flat-shaded 2D sprites; it breaks down on textured/3D
  content), needs its own per-game calibration on top of §8's reward calibration, and doesn't fit a
  fixed-shape `Box` observation without extra machinery (top-K padding or a permutation-invariant
  policy). If an agent needs motion or object-level structure, that's the agent's/client's own
  post-processing on top of the raster `Box` observation this env provides (e.g. via a Gymnasium
  observation wrapper) — not something `IrobotEnv` computes or ships adapters for. `obs_mode` stays
  raster-only: `Box` grayscale/color frames, optionally stacked (`frame_stack: int`, classic
  Atari-wrapper pattern — the standard, general way to give an agent implicit velocity information
  without any segmentation/tracking pipeline) or optical-flow-augmented (`include_flow: bool`, extra
  channel(s) via `cv2.calcOpticalFlowFarneback`, still image-shaped so it needs no new Gym space
  type) — both cheap, general, and left as documented extension points, not built speculatively for
  v1.

## 7. Action space

Touch-first, per the README roadmap's explicit prioritization (touch covers what Android games
actually respond to; mouse/gamepad deliberately out of scope). This section was re-derived after
checking two things directly rather than assuming: what `irobot_server` actually does with
concurrent pointers on the wire (§7.1), and how DeepMind's AndroidEnv — the closest prior art, same
problem shape — designs its action space (§7.2). Both findings changed the design.

### 7.1 Verified: the protocol already supports real concurrent multi-touch, not simulated taps

Checked directly in `irobot_server`, not assumed: `Controller.injectTouch`
(`irobot_server/app/src/main/java/com/guidebee/irobot/control/Controller.java:512`) plus
`PointersState`/`Pointer` (`control/PointersState.java`, `control/Pointer.java`) maintain a **persistent
map of up to `MAX_POINTERS = 10` concurrent pointers**, keyed by the client-chosen `pointer` id in
each `CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT` message (§ wire format in
[`tools/README.md`](../tools/README.md#protocol-reference)). Every touch message updates *one*
pointer's `(x, y, pressure, up/down)` state; `PointersState.update()` then rebuilds the *entire*
current set of active pointers into `MotionEvent.PointerProperties[]`/`PointerCoords[]` arrays, and
`Controller.injectTouch` synthesizes a single Android `MotionEvent` covering all of them —
correctly using `ACTION_POINTER_DOWN`/`ACTION_POINTER_UP` with the pointer index shifted into the
action code for the 2nd+ pointer (`Controller.java:555-559`), exactly matching how a real multi-finger
touchscreen event is built. This is the same mechanism scrcpy uses upstream; it is **genuine
simultaneous multi-touch** (pinch, two-finger rotate, multi-finger chords), not one-pointer-at-a-time
faking. Two implications for the Gym design:

- The wire-level *unit* stays single-pointer-per-message regardless of what the Gym action space
  looks like: a "two-finger pinch" action, however it's exposed at the `gymnasium.Env.step()` API,
  still has to become **two separate `touch_message()` writes** on the control socket (one per
  `pointer` id) for the server's `PointersState` to combine them correctly.
- That "two writes per step" case is precisely the scenario §4/§3.1's Phase-0 framing fix exists for
  — two legitimate, back-to-back JSON writes on the same socket are exactly what can coalesce into
  one `recv()` and break `json::accept`'s whole-buffer parsing. Any multi-pointer action tier below
  is a hard *requirement* on Phase 0 landing first, not just a nice-to-have.
- `env.py` (or `connection.py`) must mirror a reduced form of the server's own `PointersState`
  bookkeeping: track which `pointer` ids are currently "down" for the life of an episode, refuse to
  emit a `LIFT` for a pointer id that was never touched (malformed action → no-op, not a wire error), and
  explicitly send `UP` for every still-held pointer before `reset_episode()` tears down the app —
  otherwise a phantom held finger leaks into the next episode's launch.

### 7.2 Prior art: AndroidEnv deliberately keeps the *primitive* action single-pointer

DeepMind's AndroidEnv ([arXiv:2105.13231](https://arxiv.org/abs/2105.13231),
[repo](https://github.com/google-deepmind/android_env)) — already cited in §8.1 as the closest
existing system to this one — uses a **single-pointer** raw action per env step: a discrete
`{TOUCH, LIFT, REPEAT}` action type paired with a continuous `(x, y)` position. Multi-step gestures
(swipe, drag, scroll, and yes, pinch) are explicitly *composed* by the agent issuing a sequence of
these single-pointer primitives over consecutive steps — e.g. a swipe is `TOUCH` then several
gradually-shifted positions then `LIFT`, learned as a temporally-extended policy rather than exposed
as a single hand-authored "swipe" action. Their own paper notes this composability is deliberate: it
keeps the action space small and applies uniformly across every app/game without per-app action
engineering. This is independent confirmation of what irobot's own README roadmap already leans
toward (touch-first, keep the primitive minimal) and is the model to follow here, **with one
addition this project can afford that a general-purpose Android-OS-level agent platform can't**:
because the target here is specifically *games*, and a real (if hard) minority of games genuinely
need simultaneous multi-finger input (pinch-zoom camera controls, two-finger special moves) where
forcing the agent to discover "hold pointer 0 while also touching pointer 1" purely through
single-pointer-primitive exploration is a much harder credit-assignment problem than just giving it
the primitive — §7.3's Tier 1 exists for exactly that minority, opt-in, not default.

### 7.3 Design: single-pointer primitive by default, multi-pointer as an opt-in per-game tier

**Tier 0 (v1 default) — single active pointer, discrete.** `Discrete(N)`: an N-point tap/move grid
over the (announced, per §4.2) screen resolution combined with a small `{TOUCH, MOVE, LIFT}` action-type
set — directly modeled on AndroidEnv's primitive (§7.2), always targeting `pointer_id = 0`. A tap is
`TOUCH` then `LIFT` on the same step, or `TOUCH` then `LIFT` on consecutive steps; a swipe/drag is
`TOUCH` then several `MOVE`s toward the target then `LIFT` — composed over multiple `step()` calls,
no separate "swipe" action needed. Plus a small fixed keycode set (BACK, HOME, ENTER) as extra
discrete actions. Cheapest to get an SB3 `PPO`/`DQN` baseline running, smallest action space, matches
both AndroidEnv's precedent and most mobile-game RL write-ups' starting point.

**Tier 0.1 — continuous single pointer.** `Dict({"action_type": Discrete(3), "position": Box(2)})`
(still `pointer_id = 0` only) — same primitive-composition idea as Tier 0, continuous coordinates
instead of a grid cell, for precision-aiming games where grid resolution becomes the bottleneck.
Still one wire message per `step()`, no Phase-0 framing dependency.

**Tier 1 (opt-in, per-game config) — a second, always-present pointer.** For the minority of games
that need genuine two-finger gestures: `Dict({"pointer0": {action_type, position}, "pointer1":
{action_type, position}})`, i.e. two independent primitives issued together as one env `step()` →
two `touch_message()` writes sent back-to-back (requires Phase 0, per §7.1) that the server's
`PointersState` combines into correct `ACTION_POINTER_DOWN`/`MOVE`/`ACTION_POINTER_UP`-sequenced
`MotionEvent`s. Selected per-game via the `ActionMap` config below — most games stay on Tier 0 and
never pay the doubled action dimensionality.

**Tier 2 (documented extension point, not built) — up to N pointers.** Generalizes Tier 1 to K
configurable simultaneous pointers (K ≤ `PointersState.MAX_POINTERS = 10`, verified §7.1) for the
rare game needing 3+ finger chords. Pure Python/`spaces.py` work if a real game ever needs it — no
C++ or `irobot_server` change required, the server-side capacity already exists.

**Per-game action config**: since different games need different discrete action sets/tiers, define
a small YAML/JSON schema (`ActionMap`) that `env.py` loads at construction time — `tier: 0|0.1|1|2`
plus tier-specific params (grid size, keycode list, pointer count) — the plug-in point analogous to
the `GameAdapter` config in §8, so wrapping a new game is "write a config," not "write a new env
subclass," and Tier 1/2's cost is opt-in rather than paid by every game.

## 8. Reward and episode boundaries — a tiered, pluggable signal architecture

The README roadmap is explicit that this is not solvable generically (no standard Android
"game score" signal). This section was researched against existing prior art before designing
further — the findings changed the design, most importantly by demoting OCR from "the solution" to
"one tier among several, and not the first one to reach for."

### 8.1 Prior art that shaped this design

- **DeepMind's AndroidEnv** (Toyama et al., *AndroidEnv: A Reinforcement Learning Platform for
  Android*, [arXiv:2105.13231](https://arxiv.org/abs/2105.13231),
  [repo](https://github.com/google-deepmind/android_env)) is the closest existing system to this
  one — same problem shape: arbitrary Android apps/games, a universal touchscreen action interface,
  pixel observations. Its task-definition mechanism (a `Task` protobuf) gets reward/episode-reset
  signals from **Android's own instrumentation**: log messages the app (or an ad/analytics SDK
  inside it) already emits to logcat, matched by task-supplied patterns, and/or the **Android
  Accessibility Service** reading the on-screen view/node tree. Computer vision is not the primary
  mechanism in the reference design for this exact problem class — instrumentation is tried first,
  vision is the fallback for apps that exposes nothing else. That ordering is the single most
  important thing to import into this plan.
- **DQN** (Mnih et al., [*Playing Atari with Deep Reinforcement Learning*](https://www.cs.toronto.edu/~vmnih/docs/dqn.pdf))
  used the **change in score between consecutive frames** as the reward, not the absolute score, and
  clipped it to `{-1, 0, +1}` by sign — specifically so one reward scale and one set of
  hyperparameters worked across ~50 Atari games with wildly different scoring conventions. This is
  the same "different games, different score scales" problem stated in the user's question, already
  solved once, and directly reusable here: **delta, not absolute value; clip/normalize, don't hand
  raw magnitudes to the agent.**
- Practical write-ups on OCR-as-reward for game agents converge on two points worth designing around:
  (a) general-purpose OCR (Tesseract) has a well-known digit-confusion failure mode at small,
  stylized HUD text (`1↔l`, `7↔/`, `3↔8`), and (b) a common, cheaper workaround already used in
  shipped mobile-game RL projects is to reward "the score region visibly changed" as a binary signal,
  rather than trust a parsed digit value — it gives up knowing *how much* the score changed but is
  far more robust to misreads.
- Fixed-glyph template matching (`cv2.matchTemplate` against a small set of pre-captured digit
  images) is reported to reach high precision on game HUD/object recognition specifically because a
  given game's HUD font is static and pixel-exact, unlike OCR's general-purpose print/handwriting
  problem — this is the standard trick for reading digital scoreboards and should be the default
  *vision-tier* score reader here, with Tesseract as a fallback for fonts that don't template-match
  cleanly (anti-aliased, unusual character sets, thousands separators, "12.3K"-style abbreviations).
- **Verified: no logcat plumbing exists anywhere in this stack today.** Checked directly, not
  assumed: grepping `src/` in both this repo and upstream `scrcpy` for `logcat` turns up nothing but a
  comment in `Ln.java` (`util/Ln.java`, present near-identically in scrcpy, `irobot_server`, and
  inherited by this project) explaining that the mirroring server's *own diagnostic logs* happen to be
  visible via `adb logcat` — not a feature for capturing or forwarding the *mirrored app's* log
  output. `adb` usage in `src/core/device_server.cpp`/`irobot_core.cpp`/`android/file_handler.cpp` is
  limited to `push`/`forward`/`reverse`/`shell` for launching the server APK. So `LogcatScoreSignal`/
  `LogcatTerminalSignal` (§8.3.1/§8.4.1) is new capability, not a wire-up of something already there —
  but it needs **zero changes to irobot's C++ or the `irobot-server` APK**: `adb logcat -s <serial>`
  is a standalone command any process can shell out to, so it belongs entirely in
  `tools/irobot_gym/`, independent of the AgentManager sockets this plan otherwise builds on.

### 8.2 Two pluggable interfaces, not one `GameAdapter` blob

Split what was one interface in the earlier draft of this plan into two, because they vary
independently — a game might have a great terminal signal (a distinctive "Game Over" screen) and no
readable score, or vice versa:

```python
class ScoreSignal(ABC):
    """Emits a reward contribution per step. Delta-based, not absolute — see §8.1."""
    def read(self, frame: np.ndarray, info: dict) -> ScoreReading: ...
    # ScoreReading = a tagged union: Value(int|float) | Changed(bool) | Unavailable

class TerminalSignal(ABC):
    def read(self, frame: np.ndarray, info: dict) -> TerminalReading: ...
    # TerminalReading = {terminated: bool, truncated: bool, confidence: float}

class GameAdapter:
    """Per-game config: which ScoreSignal + TerminalSignal to use, plus reset_episode()."""
    score_signal: ScoreSignal
    terminal_signal: TerminalSignal
    def reset_episode(self, adb_client) -> None: ...  # e.g. `am force-stop` + `am start`, tap "retry"
```

`env.py` owns composing `ScoreReading`/`TerminalReading` into the Gym 5-tuple (§8.4); adapters only
report what they observed, never compute the final scalar reward — that keeps the clipping/scaling
policy (§8.4) in one place instead of duplicated per adapter.

### 8.3 `ScoreSignal` tiers, in order of preference — pick the cheapest one that works per game

1. **Logcat regex** (`LogcatScoreSignal`) — tail `adb logcat` filtered by a per-game regex, e.g. `Score:\s*(\d+)` or a
   JSON-ish analytics line many games already emit for their ad/analytics SDK even in release builds
   (`level_complete`, `post_score`, `game_over`). **Zero vision cost, zero calibration once the
   pattern is found.** First integration step for any new game should just be `adb logcat | grep -i
   score` while playing manually — if something useful shows up, this tier alone may be the entire
   reward implementation for that game.
2. **Accessibility / view-hierarchy** (`AccessibilityScoreSignal`) — `adb shell uiautomator dump` (no
   APK change) or, if that proves too slow at step-rate, an optional accessibility hook added to the
   already-deployed `irobot-server` APK that streams matched node text back over the control channel's
   currently-unused device→agent direction (bigger lift; stretch goal, not v1). **Only works for
   games whose UI is native Android views** — most game-engine titles (Unity/Cocos2d/Unreal) render
   everything into one opaque `GLSurfaceView`/`SurfaceView`, in which case this tier reports
   `Unavailable` and the pipeline falls through to vision.
3. **Digit-template matching** (`DigitTemplateScoreSignal`, vision, primary default when 1–2 are
   unavailable) — crop a configured ROI, binarize (Otsu threshold), segment into per-digit blobs via
   `cv2.findContours`, match each blob against ~10 pre-captured glyph templates (one-time,
   per-game/per-font calibration — a short `tools/irobot_gym/calibrate_digits.py` script that lets an
   integrator click-crop each digit 0–9 from a paused frame is worth building alongside this).
   Reliable, cheap at step-rate, and avoids Tesseract's small-text misread modes (§8.1) because it's
   matching against that exact font, not a general character set.
4. **OCR fallback** (`TesseractScoreSignal`) — `pytesseract` with `--psm 7 -c
   tessedit_char_whitelist=0123456789` restricted to the same ROI, for fonts that don't
   template-match cleanly (anti-aliasing, thousands separators, abbreviated notation). Document the
   known misread modes (§8.1) in the adapter's docstring so integrators know to prefer tier 3 when
   possible.
5. **"Score changed" binary fallback** (`RegionChangedScoreSignal`, vision, lowest effort) — no digit
   parsing at all: hash (reuse `computePHash`) the score ROI each step and emit `Changed(True)`
   whenever it differs from the previous step by more than a noise threshold, mapped to a fixed
   `+reward_unit`. Cannot tell *how much* score changed, but needs no per-game calibration and is
   immune to digit-misread noise entirely — the right default while a game is still being wired up,
   or when no font-consistent digit region can be found at all.

**`HealthBarFillRatioSignal`** (vision, same cost tier as 5, worth calling out separately) — for
real-time shooting/fighting games specifically (see §1.1.5): crop a configured HP/mana/ammo bar ROI,
threshold on the bar's fill color, and use the filled-pixel fraction directly as a continuous score
reading (or its per-step delta). No digit parsing, no OCR, no template calibration beyond one ROI —
and unlike digit reading, a fill-ratio is naturally continuous and low-noise, arguably the single
best-fit `ScoreSignal` for this project's stated target genre.

### 8.4 `TerminalSignal` tiers — same ordering logic

1. **Logcat regex** — an app crash, activity-finish, or an explicit `game_over`/`level_failed`
   analytics line is often already in logcat; same `adb logcat` tail as §8.3.1, different pattern.
2. **Accessibility** — a native "Game Over" / "Retry" dialog is visible in the view hierarchy even
   for some game-engine titles that fall back to a native Android dialog for post-game UI.
3. **Template match** (`TemplateMatchTerminalSignal`, vision, primary default) — `cv2.matchTemplate`
   against 1–3 integrator-supplied screenshots of known end/retry screens. This was already the plan
   from the earlier draft and remains the recommended vision-tier default: cheap once captured, and
   unlike score reading, terminal detection doesn't need a *value*, just a *match*, so there's no
   digit-misread analogue to worry about.
4. **Heuristic fallback** (`PHashStuckTerminalSignal`) — `truncated=True` (never `terminated=True` —
   see the bootstrapping note below) after N consecutive near-zero-Hamming-distance frames, reusing
   the phash stream already sent today. This is a safety net so episodes can't run forever before an
   integrator has captured real terminal templates, not a substitute for a real terminal signal.

**`terminated` vs. `truncated` matters for training, not just Gym API compliance**: SB3/most modern
algorithms bootstrap the value function across a `truncated` boundary (episode cut off by a time/stuck
limit, not a real end-of-episode) but not across `terminated` (a real death/game-over). Getting tier-4
wrong (marking a stuck-frame timeout as `terminated`) silently teaches the agent that a stall is as
bad as dying — an easy, hard-to-notice bug, worth a unit test asserting the two never get swapped.

### 8.5 Reward composition and the same-scale-across-games problem

`env.py`'s reward composer, informed by §8.1's DQN precedent:

- `Value(score_delta)` readings → `reward += clip(score_delta, -max_delta, +max_delta) * score_scale`
  — never the absolute score (an early-episode point and a late-episode point should look similar to
  the agent, matching DQN's rationale). `max_delta`/`score_scale` are per-`GameAdapter` config, so one
  game's "+50 for a coin" and another's "+50000 for a combo" both land in a comparable range without
  hand-tuning downstream code — but leave the actual cross-game *normalization* to a standard wrapper
  (SB3's `VecNormalize`, or Gym's `NormalizeReward`) rather than reinventing running statistics here;
  the adapter's job is just "don't emit an implausible spike," not "produce a globally normalized
  number."
- `Changed(True)` readings (tier-5 score fallback) → flat `+reward_unit`, no delta math applies.
- `Unavailable` readings → `reward += 0` for that step, never a guess — an adapter that can't read the
  score should say so, not fabricate a value (same principle DQN's clipping serves: don't let a bad
  sample destabilize training).
- Terminal detected → add a configurable `terminal_penalty` (commonly negative, e.g. `-1.0`) on top of
  whatever score delta fired that step, then set `terminated=True`.
- Optional `survival_bonus` (small constant per non-terminal step) as a documented extension for games
  with **no usable score or terminal signal at all** yet (tiers 1–5 of §8.3 all `Unavailable`) — turns
  "stay alive longer" into the only trainable signal, explicitly a weak fallback, not a default.

### 8.6 Noise/robustness handling specific to vision-tier score reading

Two failure modes are common enough with digit-template/OCR reading to handle explicitly rather than
let corrupt an episode's return:

- **Score resets to 0 on death, read *before* the terminal screen/template fires** — a naive delta
  would register as a huge negative reward for the death itself, double-penalizing on top of
  `terminal_penalty`. Rule: if `new_score < old_score` and `TerminalSignal` did **not** also fire this
  step, treat it as a reset artifact and emit `Unavailable` for that step rather than a negative delta;
  if `TerminalSignal` did fire, use `terminal_penalty` alone and drop the (spurious) score delta.
- **Digits mid-animation (count-up/roll effects) sampled at an arbitrary step boundary** — either
  gate score reads on `PHashStuckTerminalSignal`'s inverse (only read once the *frame*, not just the
  ROI, has been stable for ≥1 extra tick) or accept the per-step noise and rely on it washing out over
  an episode's cumulative return; document this as a known, bounded noise source rather than something
  the adapter tries to eliminate perfectly.

### 8.7 What ships in `adapters/` initially

Given §8.3–8.4, the concrete v1 set (all already implied by existing infra, no new C++):

1. `PHashStuckTerminalSignal` (fallback safety net, §8.4.4).
2. `TemplateMatchTerminalSignal` (primary vision-tier terminal detector, §8.4.3).
3. `RegionChangedScoreSignal` (lowest-effort vision-tier score signal, §8.3.5).
4. `DigitTemplateScoreSignal` + `calibrate_digits.py` (primary vision-tier score reader once a game's
   HUD font is calibrated, §8.3.3).
5. `HealthBarFillRatioSignal` (§8.3) — cheap, continuous, and the best-fit default for the shooting/
   fighting genre this project's feasibility case (§1.1.5) targets; worth shipping alongside 3–4
   rather than treating as an extension point.

`LogcatScoreSignal`/`LogcatTerminalSignal` (§8.3.1/§8.4.1) are the cheapest to build and should
genuinely be tried **first** against a real target game (a `grep` while playing manually costs
minutes) before writing any vision code for that game — but they're per-game-regex, not shippable as
a generic reference adapter the way the phash/template ones are, so they belong in the integration
docs/examples rather than the default `adapters/` set. `TesseractScoreSignal` (§8.3.4) and the
Accessibility tiers (§8.3.2/§8.4.2) are documented extension points, not built speculatively until a
real game needs them.

## 9. `reset()` / `step()` mechanics

- **`reset()`**: adapter's `reset_episode()` (typically `adb shell am force-stop <pkg> && am start
  <activity>` via the existing `platform/net.hpp`-adjacent ADB tooling patterns, driven from Python
  via `subprocess`/`adb` directly — no new C++ needed), then block on the frame reader until N
  consecutive frames are phash-stable (reuse `PHashStuckTerminalSignal`'s logic inverted: wait *for*
  stability, not truncate on it), then return `(obs, info)`.
- **`step(action)`**: encode action → `protocol.py` message → send on control socket → wait for the
  next fresh frame per §6's staleness tracking (bounded by a configurable `step_timeout`) → run the
  configured `ScoreSignal`/`TerminalSignal` (§8.3–§8.4) → `env.py` composes the reading into the
  reward per §8.5 → return the 5-tuple.
- **`action_repeat`/frame-skip**: expose as a constructor param (classic Atari-wrapper pattern) since
  Android UI reaction latency will usually exceed one video frame interval.
- **Headless operation**: `irobot` currently always opens an SDL window unless `--no-display` is
  combined with `--record` (see README Usage). Confirm at implementation time whether
  `--no-display` alone (no recording) is a supported combination for agent-only runs — if not,
  that's a one-line C++ CLI-parsing fix, not a design change, and belongs in Phase 0 if discovered
  early enough to bundle.

## 10. Parallel rollouts

Document, don't over-engineer: a `VecEnv` is just N `IrobotEnv`s, each pointed at one `irobot`
process with a distinct `--serial` (device/emulator) and distinct `--port` (agent ports derive from
it, per existing `AgentManager::Init`). `launcher.py`'s job is only to spawn/track those N
subprocesses and hand back N `(host, port)` pairs — `gymnasium.vector.AsyncVectorEnv` or SB3's
`SubprocVecEnv` handle the actual parallel `step()` orchestration once each `IrobotEnv` exists.
Operational caveat to document, not solve: a single `adb` server is shared across all instances, and
emulator instances are the realistic scaling bottleneck (CPU/RAM), not the socket protocol.

## 11. Testing strategy

- `test_protocol.py`: encode/decode round-trips against fixed byte fixtures captured from a real
  session (no socket, no device) — catches wire-format drift if C++ side changes.
- `test_env_checker.py`: `gymnasium.utils.env_checker.check_env(env)` against `connection.py` mocked
  to replay a canned sequence of `BlobMessage`s — validates Gym API conformance without hardware.
- Manual integration checklist (real device/emulator required, do by hand before calling a phase
  done): `reset()`→`step()` loop for 100+ steps with no stall (validates Phase 0's framing fix under
  load), one full episode via a reference adapter ending in `terminated=True`, one `SubprocVecEnv`
  run with 2 parallel `irobot` instances against 2 emulators.

## 12. Suggested build order (each step independently mergeable/testable)

0. **Latency benchmark spike, before anything else** (§1.1.1) — a throwaway script that sends a touch
   through the existing agent control socket and counts frames on the existing agent video socket
   until a known on-screen element visibly responds. No new package, no C++ change — this uses
   protocol capability that already exists today. Its output (a real round-trip number) determines
   whether the real-time-shooting/fighting target from §1.1 is realistically in reach before investing
   in steps 1–8; treat a bad number as a reason to retarget genre, not a reason to skip this step.
1. Phase 0.1 — length-prefixed control framing (C++). Verify with `agent_client.py` updated to match.
2. Phase 0.2 — resolution-announcement blob message (C++), drop `--screen-size` requirement from
   `agent_client.py`'s `interactive`/`record` as a side benefit.
3. `protocol.py` extraction + `test_protocol.py`; refactor `agent_client.py` to use it (behavior
   unchanged, pure refactor, easy to review).
4. `connection.py` (background frame reader) + `env.py` skeleton with **Tier 0 only** (§7.3, single
   pointer, discrete tap grid), grayscale observation, no reward/episode-boundary logic yet
   (`reward=0`, `terminated=False` always) — get `check_env()` passing first. Tiers 0.1/1/2 stay
   documented-not-built until Tier 0 is validated end-to-end against a real device; Tier 1
   additionally can't land before step 1 (Phase 0.1 framing fix) per §7.1.
5. `adapters/base.py` (`ScoreSignal`/`TerminalSignal`/`GameAdapter`, §8.2) +
   `PHashStuckTerminalSignal`, wire into `reset()`/`step()`.
6. Manual validation against one real, simple game: **first** `adb logcat | grep -i score` while
   playing it by hand (§8.3.1/§8.7) — if a usable log line exists, wiring `LogcatScoreSignal` is
   cheaper than everything below and worth 10 minutes before writing any vision code. Otherwise fall
   back to `TemplateMatchTerminalSignal` + `RegionChangedScoreSignal`/`HealthBarFillRatioSignal`
   (§8.7), then `DigitTemplateScoreSignal` + `calibrate_digits.py` once tap-only baselines work
   end-to-end.
7. `launcher.py` + 2-instance `SubprocVecEnv` validation.
8. `examples/train_ppo.py` as the "does this actually train" smoke test.

Steps 1–2 are the only ones that touch the C++ codebase; everything else is additive Python. This
was deliberately ordered so the highest-risk/most-invasive change (protocol framing) happens first
and small, while it's still easy to reason about — and step 0 comes before even that, because it can
invalidate the genre assumption the rest of the plan is aimed at before any of it is built.

## 13. Further considerations (backlog — not actively designed)

Ideas surfaced during planning that are worth recording for a future contributor but weren't
developed to the same depth as §4–§12 — treat this as a prioritized backlog, not a spec.

**Throughput & determinism**

- **Fast resets via emulator snapshots.** §9's `reset()` (`am force-stop` + `am start`, wait for
  phash-stability) is slow — seconds per episode. On an emulator backend (not a physical device), VM
  snapshot/restore gives near-instant resets and is the standard throughput trick for this kind of
  training loop; worth an emulator-specific `reset_episode()` path once §1.1's latency spike confirms
  the project is worth scaling up.
- **Separate "training" vs. "human-mirroring" capture settings.** Lower `--max-fps`/`--bit-rate`/
  `--max-size` (flags already exist) for training runs — RL doesn't need human-viewing quality, and
  every millisecond shaved off encode/network/decode compounds across millions of steps (§1.1.3).
- **Standardize latency/telemetry in `info`.** `info["step_latency_ms"]` alongside the already-planned
  `info["frame_age_steps"]` (§6), so `step_timeout` and throughput can be tuned from real numbers
  instead of guessed at — directly follows from making step 0's benchmark a habit, not a one-off.

**Safety & robustness on a real device**

- **Ads, interstitials, and OS dialogs will happen** on real F2P games. None of §8.4's `TerminalSignal`
  tiers currently handle "unexpected screen that's neither gameplay nor a known game-over" — worth a
  generic watchdog (frame matches no known state for N steps → press BACK, don't just truncate).
- **Guardrail the action space away from real-world side effects.** This drives a real device, possibly
  a real account — an untrained agent tapping randomly can hit an ad's outbound link or an in-app-
  purchase button. Restrict the touch grid (§7) to the actual play area per-game as a documented
  safety default, not an afterthought.

**Reuse what already exists**

- **Imitation-learning warm start, nearly free.** `Ctrl+E`/`events.json` and `agent_client.py
  record`/`play` already produce exactly the demonstration format a behavior-cloning pretrain step
  wants — strong synergy for sparse-reward or hard-exploration games (real-time fighting/shooting
  plausibly qualifies, per §1.1), and it's existing infra, not new build.
- **Export Gym episodes back to the existing replay format** so a human can watch what a trained agent
  actually did via `agent_client.py play` — cheap, reuses infra, high debugging value.

**Prove the architecture, don't leave it abstract**

- Ship 2–3 fully worked `ActionMap` + `GameAdapter` configs for real, freely available games as both
  documentation and CI regression fixtures — right now the plugin design (§7/§8) is proven only on
  paper.

**Stretch**

- Since action/observation/reward are already game-agnostic via config, a multi-game curriculum
  wrapper training one generalist policy is a natural, interesting follow-on research direction once
  single-game training works.
