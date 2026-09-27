# typesafe-agent — a Jev-driven decision loop over a Gym IDE project

Status: **prototype**. Connects to a live `irobot` process's AgentManager sockets (the same
two ports [`tools/agent_client.py`](../tools/README.md) and
[`irobot_gym_ide`](../irobot_gym_ide/README.md) use), loads a Gym IDE project's `ActionMap`,
and runs a tick-based decision loop that asks TypeSafe's Jev model which named action to run
next. It reuses `irobot_gym_ide.connection.LiveConnection` and `irobot_gym_ide.io.load_project`
directly rather than re-deriving the wire protocol or action-execution semantics — see those
modules for how a project's `hold_start`/`hold_stop`/`momentary`/`macro` actions actually get
sent as touch/key events.

It grew out of a comparison with [`typesafe-mario`](https://github.com/guidebee/typesafe-mario)
(a TypeSafe/Jev agent that plays the original NES Super Mario Bros via emulator RAM) for
`super-morse`'s own Mario-style platformer, Ampere's Run. The
[`irobot_gym_ide/examples/mario_platformer/`](../irobot_gym_ide/examples/mario_platformer)
project is already calibrated against that exact game (see its `actions.yaml` — the touch
coordinates and descriptions cite `PlatformerCommand`, `TouchOrKeyboardInput`, and
`Player.applyJump()` by name), which is what this tool was built to drive.

## What this is (and isn't)

- **Real device, real input.** Actions run as real ADB-injected touch/key events against the
  actual, unmodified app — no code changes to the target game, same as the rest of `irobot`.
- **Thin observation, on purpose.** Unlike `typesafe-mario`'s exact RAM-derived position/
  velocity/collision-grid telemetry, the only signal available today is a perceptual-hash
  "did the screen change since the last decision" flag (`docs/opengym_implementation_plan.md`
  §8's reward/HUD/OCR extraction is **not yet built**). Jev is choosing near-blind — enough to
  exercise the control loop end-to-end, not a real playing strategy. See `policy.py`'s module
  docstring.
- **Not a Gym/Gymnasium `Env`.** That's a separate, not-yet-built piece
  (`docs/opengym_implementation_plan.md`); this tool talks to the same sockets directly.

## Setup and run

```bash
pip install -r requirements.txt        # PyYAML always; typesafe-sdk for the `typesafe` policy
./typesafe_agent.sh state-demo irobot_gym_ide/examples/mario_platformer/project.yaml
```

`state-demo` just lists a project's actions — no device connection, no API calls:

```
Project 'mario_platformer_example': 11 action(s) at 127.0.0.1:27183
  down_start      [hold_start] Hold the touchpad knob dragged down (pointer 0) ...
  fire            [momentary ] Tap Button A (isButtonAPressed -> PlatformerCommand.actionPressed) ...
  jump            [momentary ] Tap Button B (isButtonBPressed -> PlatformerCommand.jumpPressed).
  long_jump       [macro     ] ...
  ...
```

With `irobot` running and a device/emulator connected (see the [main README](../README.md) for
launching `irobot` itself), measure the control loop's actual round-trip latency **before**
trusting the decision loop — this is `docs/opengym_implementation_plan.md` §1.1's explicit
first-validation-step recommendation, not yet measured anywhere in this repo:

```bash
./typesafe_agent.sh latency-check irobot_gym_ide/examples/mario_platformer/project.yaml --action jump
```

Then run the live decision loop (requires `TYPESAFE_API_KEY` for the default `typesafe` policy;
`--policy heuristic` needs neither a key nor `typesafe-sdk`, and is the way to smoke-test the
connect/decide/act/log loop on its own):

```bash
./typesafe_agent.sh play irobot_gym_ide/examples/mario_platformer/project.yaml --policy heuristic
./typesafe_agent.sh play irobot_gym_ide/examples/mario_platformer/project.yaml --decision-interval-ms 250
```

Each decision is appended to `artifacts/run-<timestamp>.jsonl` (observation, chosen action,
confidence, latency, any skipped events) as it happens, same spirit as `typesafe-mario`'s own
run log.

## Testing

Pure-Python, no live device or Qt required:

```bash
python -m unittest discover -s typesafe_agent/tests -t .   # from the repo root
```

## File layout

```
typesafe_agent/
├── policy.py     # Decision, Policy protocol, TypeSafePolicy (Jev), HeuristicPolicy (offline)
├── runner.py     # the decision loop: connect, observe, ask policy, run_action, log
├── latency.py    # docs/opengym_implementation_plan.md Sec 1.1's latency benchmark
├── cli.py        # state-demo / latency-check / play
└── tests/          # policy, hold-bookkeeping, latency-math, and a real-project state-demo smoke test
```

## Known limitations / next steps

- **Hold bookkeeping assumes a `*_start`/`*_stop` naming convention** (see `runner._update_holds`).
  True for `mario_platformer`'s actions, not guaranteed by the `ActionMap` schema itself.
- **No reward signal.** A won/lost/progress-made signal (score OCR, a health-bar fill ratio, an
  `ImageTemplate`/`Compare`-node check per `irobot_gym_ide`'s own Compare Templates feature)
  would let Jev do far better than reacting to "did the screen change" alone.
- **One action per decision, not per frame.** Matches `typesafe-mario`'s own multi-frame decision
  window (there: 8 emulator frames per macro), but the right interval here is unmeasured — that's
  exactly what `latency-check` is for.
- **`TypeSafePolicy`'s prompt is generic** (no fixed goal/geometry/timing detail the way
  `typesafe-mario`'s `ACTION_DESCRIPTIONS`/prompt sections are, since there's no structured
  terrain/hazard telemetry here to reference yet). Once a reward/state-extraction step exists,
  the prompt should grow the same kind of guidance `typesafe-mario`'s `policy.py` has.
