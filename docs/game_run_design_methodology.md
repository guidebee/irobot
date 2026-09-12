# Game Run Design Methodology — from level data to a verified action sequence

Status: **first pass complete and applied once** (`examples/mario_platformer`'s `level_1_1_clear`
Game Run), written up here so the next level — and the next game entirely — doesn't have to
rediscover the same two bugs by hand. Companion to
[`irobot_gym_ide/docs/ACTION_CLASSIFICATION_DESIGN.md`](../irobot_gym_ide/docs/ACTION_CLASSIFICATION_DESIGN.md)
(how the *Action library* itself gets built) and
[`opengym_implementation_plan.md`](opengym_implementation_plan.md) (where this whole exercise is
actually headed — see §8 below). This doc is about the part neither of those covers: once you
have an Action library and a HUD/button map, how do you actually *script a level clear* out of
them, and how do you know the script is safe before you ever run it against a real device?

## 1. What this is, and why it needed writing down

A Game Run (`model.GameRun` — ACTION/DELAY/REPEAT/COMPARE/FIND_TEMPLATE/ASSERT nodes) is, in its
simplest and most common shape for a platformer, an **open-loop script**: hold a direction, wait N
frames, tap jump, wait more, release. Nothing about the node-graph editor stops you from picking N
by eyeballing a screenshot or a level minimap — but "jump somewhere near where the level atlas says
an enemy is" turned out to be exactly wrong twice in the same short exercise (`level_1_1_clear`,
built against `au.com.guidebee.morsetoolkit`'s Mario port at `C:/workspace/morsecode`, level
`level_11.json` = World 1-1):

1. **Every ground enemy in that level was actually walking toward Mario**, not sitting still at its
   spawn tile, so "jump near tile 95" fired 95 frames too late — Mario would have already run into
   the enemy well before the scripted jump.
2. **A second `jump` tap while still airborne is a silent no-op** (the port's jump is a single
   edge-triggered impulse, gated on `onGround`), so two hazards scheduled closer together than one
   jump's real air time were unknowingly sharing one arc — and in one case (a gap right after an
   enemy encounter) that shared arc would have landed Mario about 1.5 pixels before the pit's edge.

Neither bug was visible by looking at the level's tile positions alone. Both were only found by
actually simulating the game's own physics and the enemies' own AI from source, then checking the
schedule against that simulation frame-by-frame. That's the actual content of this doc: a
repeatable procedure for getting to a schedule that's *verified*, not just *plausible*.

## 2. Prerequisites

Before scripting a single jump, make sure these three things exist and have been *read*, not
assumed:

1. **An Action library and HUD region map** for the target game, per
   `ACTION_CLASSIFICATION_DESIGN.md` — named, reusable touch primitives (`right_start`/`right_stop`,
   `jump`, ...) at real, calibrated on-screen coordinates. Designing a schedule before this exists
   just means re-deriving coordinates inline, which doesn't survive the next screen-resolution
   change.
2. **The target game's own source**, specifically:
   - The player's movement/jump physics — exact constants, not "about": acceleration, max speed
     (and how a "run"/turbo modifier changes it), the jump impulse formula, gravity step and cap.
     For this port: `Player.java`'s `ACCEL`, `MAX_SPEED`/`MAX_SPEED_TURBO`, `JUMP_BASE`,
     `JUMP_SPEED_BONUS_DIVISOR`, `GRAVITY_STEP`, `GRAVITY_CAP` — all read directly out of the file,
     none guessed from playing the game by eye.
   - Every hazard type's own **behavior**, not just its placement. A static hazard (a pipe, a gap)
     only needs its position. A *mobile* hazard (an enemy) needs its own movement rule — speed,
     initial direction, what makes it turn around — read from its own class, not inferred from the
     level editor's placement icon.
3. **The level's raw data**, not a hand-written summary of it. `docs/mario/MARIO_LEVEL_ATLAS.md`'s
   own auto-generated "ground structure" line for World 1-1 didn't match the level's actual
   `stone` tile spans when checked directly against `level_11.json` (it described a 22-tile gap that
   isn't in the raw ground-tile data at all) — a derived doc is a convenience for a human reading
   about the level, not a substitute for parsing `tiles`/`checkpoints` yourself when the output is
   going to be a script that runs unattended.

## 3. The methodology

### 3.1 Establish ground truth from source

Read, don't assume:
- The player's own update loop for how position, speed, and jump gravity are computed per frame,
  and what gates a jump (usually `onGround`, or a state flag for a water/paddle-jump variant).
- Every enemy/hazard class's own `act()`/update method for its movement rule and initial state
  (spawn-time constructor arguments especially — a hardcoded `movingRight = false` passed at
  construction is exactly the kind of fact a level-placement-only reading would never surface).
- The raw level file's tile/enemy/checkpoint arrays. Reconstruct the ground profile from the actual
  tile spans (solid segments and the gaps between them), not from a rendered minimap or a
  human-written table.

### 3.2 Build a frame-accurate simulator matching those constants

A short standalone script (Python is fine — this doesn't need to run inside the target engine,
only reproduce its arithmetic) that, given the verified constants, computes:

- **Player position/speed over time** under a given held input (e.g. "hold right + run from a
  standing start"): `speed = min(speed + ACCEL, MAX_SPEED)` per frame, `position += speed / 20` per
  frame (that `/20` divisor is this specific port's own unit convention — check the equivalent in
  whatever engine you're targeting).
- **Player height-over-time after a jump** (a "rise profile"): starting gravity from the jump
  impulse formula at the current speed, then `gravity = min(gravity + GRAVITY_STEP, GRAVITY_CAP)`
  each frame, accumulating `-gravity` into a running "rise" value. This profile is what tells you,
  for any candidate jump-trigger frame, exactly how much clearance Mario has *at any later frame* —
  which is the number every "is this jump safe" question in §3.4 actually reduces to.
- **Every mobile hazard's own position over time**, using its own movement rule (constant velocity
  plus turn-around conditions, for the enemies here) from its own spawn frame — not from whenever
  Mario happens to approach it. If a hazard is dormant until some trigger (camera proximity, a
  flag), that trigger needs to be found and modeled too — verify this rather than assuming either
  "always active from level load" or "only active once nearby"; we confirmed the former for this
  engine by reading the actor base class and the spawn call site (`LevelLoader.spawnEnemies`,
  `Enemy.act`) and finding no dormancy/visibility gate at all, not by assuming it.

### 3.3 Compute the real encounter frame for every hazard

For a static hazard (a gap, a raised obstacle), this is just "the frame at which the player's
simulated position reaches the obstacle's position." For a mobile hazard, solve for where the two
trajectories actually cross — in the worked example this meant simulating the enemy's own
leftward walk from frame 0 and finding where its position and Mario's position meet, which is a
very different (and, here, always *earlier*) number than "the frame Mario's position reaches the
enemy's *spawn* tile."

### 3.4 Define a per-hazard safety requirement

Not every hazard needs the same kind of safety check:
- **A raised solid obstacle** (a pipe, a wall) needs *vertical clearance*: rise-at-arrival must be
  at least the obstacle's own height in pixels. No margin needed beyond that — clearing a 4-tile
  pipe means being above 4 tiles' worth of pixels when your x-position crosses it, not "close to"
  that height.
- **A mobile ground hazard** (an enemy) needs vertical clearance over its collision-box height, plus
  a **margin for its own AI uncertainty**: turning at walls, or (for a patrol type) reversing at a
  boundary the level data doesn't spell out as cleanly as a wall tile does. We used roughly 1.5
  tiles as the floor for "safely over an enemy" rather than the enemy's exact body height, precisely
  because the enemy's own position is a simulation, not a certainty, once real device timing enters
  the picture (see §6).
- **A gap** needs the jump to still be *comfortably* airborne (or already grounded past the far
  edge) at the gap's far edge — but the real danger isn't insufficient height, it's insufficient
  **remaining air time relative to the gap's position**, because landing is a single moment: land
  one pixel short of solid ground and you fall in. Treat a gap's requirement as "verify the exact
  landing frame and position of whichever jump governs this stretch, and confirm the landing x is
  meaningfully (not by a coin-flip's margin) past the gap's far edge" — don't just check "is Mario
  still rising" the way you would for a pipe or an enemy.

### 3.5 Compute each hazard's own "latest safe trigger"

Using the rise profile from §3.2, find — for a jump timed to arrive at this hazard with maximum
lateness (i.e. the smallest lead time, keeping the jump as close to the obstacle as possible so it
costs the least "downstream" schedule room) — the smallest offset (frames since jump) at which the
rise profile first satisfies this hazard's own requirement. This is the hazard's **ideal own
trigger** if it were the only hazard in the level.

### 3.6 Schedule jumps: coast where verified safe, dedicate where not, propagate backward when tight

This is the actual scheduling algorithm, and it needs all three of the following, not just the
first (which is what produced the two original bugs):

1. **Forward pass, coast-first.** Walk hazards in x/time order. For each one, first check whether
   the *most recently scheduled* jump's own rise profile already satisfies this hazard's
   requirement at its real arrival frame (§3.3/§3.4) — if so, no new jump is needed, this hazard
   "coasts" on the existing arc. Only schedule a fresh, dedicated jump (at its own ideal trigger
   from §3.5) when coasting fails the check.
2. **Re-arm constraint.** A jump's own natural air time (simulate this — it's the frame at which
   the rise profile returns to zero) is the *minimum* spacing between two dedicated jumps: a second
   jump attempted before the first has landed is a no-op, not a queued action. If two dedicated
   triggers come out closer together than this, that's not acceptable spacing — it means one of
   them needs to move.
3. **Backward propagation, not forward delay.** When two dedicated triggers are too close, the fix
   is to move the **earlier** one earlier still (so it lands in time to re-arm for the later one),
   never to push the later one's trigger later than its own hazard requires. Pushing the later
   trigger later was the first (wrong) fix we tried — it cascades: delaying one jump delays every
   jump after it by the same amount, which very quickly produces triggers scheduled *after* the
   hazard they were meant to protect against. Moving the earlier trigger earlier instead is safe
   specifically because the rise profile is still climbing (not yet past its peak) for every offset
   small enough to matter here — earlier is *more* clearance, not less, right up until you're
   restricted only by the previous-previous jump's own re-arm time. Propagate this constraint
   backward through the whole chain of dedicated triggers before considering the schedule final.
4. **Iterate to a fixed point.** Backward propagation can turn a previously-safe coast unsafe (an
   earlier jump moved earlier to satisfy a downstream pipe may no longer cover an enemy it used to
   coast over). Re-verify every coast after each backward pass; promote any that now fail to their
   own dedicated jump; re-run the backward pass; repeat until nothing changes. This took two
   iterations for World 1-1's 15 hazards — small, but real: skipping it left one enemy encounter
   unprotected in the first "fixed" draft.

### 3.7 Translate the schedule into a Game Run graph

Each **dedicated** jump becomes one `ACTION` node (the jump action) preceded by one `DELAY` node
(the frame gap from the previous dedicated jump, or from run-start for the first one). Coasted
hazards get **no node at all** — they're documentation of *why* the schedule is safe, not steps in
the graph; put that reasoning in the authoring script's own comments/docstring (or a future
per-node annotation field, see §8) since `RunNode` has no free-text description field today.
Bracket the whole sequence with the movement/run hold actions at the start and the matching
releases at the end (`right_start`/`run_start` ... `run_stop`/`right_stop`), plus a trailing delay
past the level-end checkpoint before releasing, since the level-completion state machine typically
takes control away anyway (harmless either way, but avoids a premature release racing the
checkpoint trigger).

### 3.8 Validate twice: structurally, then physically

Structural validation is cheap and already exists — call it, always:
- `Action.validate()` / `GameRun.validate()` for referential/shape correctness.
- `model.orphan_releases`, `model.conflicting_pointer_actions`, `model.run_pointer_conflicts` for
  pointer-sharing mistakes (a `PRESS` on a pointer another action is still holding is silently
  skipped by `connection.py`, and a stray `RELEASE` can end an unrelated hold early — see
  `ACTION_CLASSIFICATION_DESIGN.md`'s own G10 for exactly this failure mode with a *recorded*
  session; the equivalent check for a *hand-authored* graph is `run_pointer_conflicts`).

But **structural validation does not catch either bug in §1** — a graph can be perfectly
well-formed (every action exists, no pointer conflicts) and still walk Mario into an enemy or a pit,
because that failure is about *timing against the simulated physics*, which `model.py` has no
opinion on at all. The physical check is the simulation from §3.2-§3.6, re-run one final time
against the *actual* frame numbers written into the `DELAY` nodes (not just the numbers you
intended to write) — a transcription slip between "the schedule I computed" and "the frames I put
in the YAML" is exactly the kind of thing that's invisible to `GameRun.validate()` and only caught
by re-deriving the schedule from the saved file and diffing.

## 4. Worked example: Level 1-1 (`level_11.json`)

Fifteen hazards on the ground path (8 enemies, 4 ascending pipes, 3 floor gaps — see the level's own
`tiles` array for the raw source), resolved to **10 dedicated jump taps**, five hazards coasting
safely on an adjacent one:

```
goomba21 -> pipe1_28 -> [goomba40 & pipe2_38] -> [goomba53 & pipe3_46] -> pipe4_57 ->
gap_69_70 -> [goomba95 & gap_86_88] -> turtle106 -> [goomba123 & goomba127] ->
[goomba173 & gap_152_154] -> flag
```

The first (wrong) draft used static enemy positions and "jump one tile before" with no re-arm
check; every subsequent number in this doc's methodology exists because that first draft, when
actually simulated end to end, would have hit an enemy on the way to the very first obstacle. The
corrected, verified version is `examples/mario_platformer/runs.yaml`'s `level_1_1_clear`; see its
authoring script's own docstring (kept alongside this repo's history, not checked in as a permanent
module — the *run* is the artifact, the script is scratch work) for the full per-hazard numbers.

## 5. Known bugs and gaps found along the way

Recorded here in the same spirit as `irobot_gym_ide_design.md` §7 and
`ACTION_CLASSIFICATION_DESIGN.md`'s own punch list — some are bugs in *our first-draft process*
(fixed by this methodology), some are real, still-open gaps in iRobot's own data model:

- **(Process bug, fixed) Static-position enemy timing.** Covered in full above — the root cause
  was designing from the level *editor's* view of enemy placement instead of the enemy class's own
  movement code.
- **(Process bug, fixed) No re-arm/air-time check.** Covered above — jump timing that "looks fine"
  spaced against obstacle x-positions can still silently rely on an unverified older jump's arc.
- **(Open gap in the data model) One physical button, two simultaneous logical signals.** This
  port's Fire/Run button fires an edge-triggered "fire" action *and* a level-triggered "run" hold
  from the exact same touch, every time, not as alternate tap-vs-hold behaviors. `HudRegion` only
  models one action (or one start/stop pair) per region; we resolved this by wiring the region to
  the hold pair (`run_start`/`run_stop`, the traversal-relevant effect) and keeping `fire` as a
  separate, directly-callable Action for a Game Run that wants a deliberate throw — but this is a
  genuine expressiveness gap for any game with a similarly overloaded button, not just a one-off
  choice for this project. Worth a real fix (e.g. a region field for "also fires this momentary
  action on press") if a second game hits the same shape.
- **(Fixed, and worth remembering why) `long_jump` was first authored as "hold the jump button
  longer."** That's a real mechanic in *some* platformers (and is `opengym_implementation_plan.md`
  §7.4's own generic example) but this port's jump is edge-triggered with no hold-duration effect —
  holding longer does nothing extra. The actual lever for a longer/higher jump here is horizontal
  speed at takeoff, so the corrected macro holds right+run to build speed *first*, then taps jump.
  **Lesson for the next game**: never port a generic macro shape from documentation or another
  game's action library without checking the actual jump-gating code first.
- **(Expected, not a bug) `conflicting_pointer_actions` flags all four `*_start` direction actions
  sharing pointer 0.** This is correct and intentional — one touchpad, one thumb, mutually exclusive
  directions — exactly the case `model.py`'s own docstring calls out as safe. Don't "fix" this by
  giving directions separate pointers; that would let a hand-authored Game Run hold left and right
  simultaneously, which the real touchpad never can.
- **(Open, structural) No reusable "level → schedule" tool exists yet.** Every number in §4 came
  from one-off Python scripts written against this specific level's JSON and this specific engine's
  physics constants. See §7 for what this should become.

## 6. Limitations of this approach — be honest about what "verified" means here

- **This is open-loop.** The entire schedule is computed once, offline, against a simulation — it
  has no way to react to the *actual* live game if reality diverges from the simulation (network
  jitter changing effective frame timing, an enemy's AI doing something the simulation didn't
  model, a missed input due to a dropped control message). "Verified" here means "verified against
  our best model of the game's own deterministic rules," not "guaranteed to work on a live device."
  A COMPARE/FIND_TEMPLATE-driven reactive graph (branching on what the live frame actually shows)
  is the real fix for this class of risk, at the cost of much more authoring work per level — a
  deliberate tradeoff, not an oversight, for a first pass.
- **The simulation assumes the engine's frame rate and this run's `time_scale` line up.** Every
  frame count here is in the *game's* logic frames, not wall-clock time; `Project.time_scale`
  (`ACTION_CLASSIFICATION_DESIGN.md` G11) exists precisely because a different device can run the
  same logic at different real speeds — a schedule built this way is only as portable as that one
  number being tuned correctly for wherever it actually runs.
- **No live device replay has confirmed this schedule yet.** Structural validation and physics
  simulation both passed; an actual `Replay`/dry-run against the real game has not been done as of
  this doc. Treat the schedule as "ready to test," not "confirmed working."
- **The enemy movement model assumes no wall/gap turn-arounds occur before the encounter.** We
  verified this by hand for World 1-1's specific ground layout (no wall or ledge lies between an
  enemy's spawn and where it meets Mario) — a general tool (§7) needs to actually simulate the
  enemy's own collision-driven turning, not just assume a clear runway.

## 7. Roadmap: turning this into reusable tooling, toward the Gym env

This methodology, done by hand, is exactly the kind of work `opengym_implementation_plan.md`'s
eventual `env.py` needs an RL agent to learn to do *adaptively* — but getting there benefits from
this same ground-truth-from-source discipline showing up as real tooling, not just a doc:

1. **A `level_compiler` module**, headless like `model.py`/`hud_classifier.py` (no Qt), that takes
   a level's raw tile/enemy/checkpoint data plus a small, declared physics-constants file (mirroring
   what §3.1 currently means "go read `Player.java` by hand") and produces the ground profile,
   obstacle list, and hazard requirements from §3.3-3.4 automatically. This turns "read the source,
   write a one-off script" into "point a tool at a level file."
2. **A reusable jump-scheduler** implementing §3.5-3.6 (coast-check, re-arm constraint, backward
   propagation, fixed-point iteration) as a library function over an abstract hazard list, not
   Mario-specific — the algorithm itself (verify-before-coast, propagate-backward-not-forward,
   iterate to a fixed point) doesn't depend on this being a Mario clone.
3. **A schedule-to-GameRun compiler**, i.e. §3.7 automated: given a verified schedule, emit the
   `RunNode`/`RunEdge` graph directly, rather than hand-writing the authoring script each time (as
   this doc's worked example did).
4. **A physics-simulation-backed dry run**, extending `dry_run.DryRunConnection`
   (`irobot_gym_ide_design.md`) so "Preview (Dry Run)" can optionally check a Game Run's *timing*
   against a supplied physics model, not just its structure — surfacing exactly the two bug classes
   in §1 automatically, at authoring time, for any hand-built or generated graph.
5. **Feed this directly into `gym_export`'s `ActionMap`** (`ACTION_CLASSIFICATION_DESIGN.md` G17):
   once (1)-(3) exist, a whole level's worth of scripted clears becomes a corpus of known-good
   action sequences — exactly the kind of imitation-learning seed data
   `opengym_implementation_plan.md` §8 doesn't yet have a source for, and a natural baseline to
   compare a trained agent against once `tools/irobot_gym/env.py` exists.
6. **Closed the open question from `opengym_implementation_plan.md` §7.4 in practice**: this
   exercise is the first real end-to-end test of the Tier 1.5 named-button model against an actual
   game's actual level data, not just the plan's own illustrative screenshot — the two bugs in §1
   are exactly the kind of thing that only shows up once you try to *use* the design for something
   real, and are worth folding back into that plan's own assumptions before `env.py` is built on
   top of them.

## 8. Quick-reference checklist for the next level

1. Read the physics constants from the player's own source. Don't reuse another level's/game's
   numbers without checking.
2. Read every hazard type's own behavior from its own class, not from the level editor's icon.
3. Parse the level's raw tile/enemy/checkpoint data yourself; don't trust a derived summary doc for
   anything that will drive a script.
4. Simulate: player position/speed over time, player rise-over-time after a jump, every mobile
   hazard's own position over time from its own spawn frame.
5. Compute the *real* encounter frame for every hazard (trajectory intersection for mobile ones, not
   spawn position).
6. Define each hazard's own safety requirement (vertical clearance for solid obstacles/enemies;
   verified landing position for gaps).
7. Schedule: coast-first, verify every coast, dedicate when unsafe, propagate backward when two
   dedicated triggers are closer than one jump's real air time, iterate to a fixed point.
8. Compile to a Game Run graph: one ACTION+DELAY pair per dedicated jump, nothing for a coasted
   hazard, hold/release actions bracketing the whole run.
9. Validate structurally (`GameRun.validate`, `orphan_releases`, `run_pointer_conflicts`) **and**
   physically (re-run the simulation against the actual saved frame numbers).
10. Be honest in the doc/commit about what wasn't checked: live-device replay, wall/ledge
    interactions the simulation didn't model, anything assumed rather than verified.
