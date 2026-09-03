# Game Run Editor — closing the gaps for real platformer play, and an AI-assist design

Status: **design doc, not yet implemented.** Companion to
[`GAME_RUN_EDITOR_GUIDE.md`](GAME_RUN_EDITOR_GUIDE.md) (the current five-node-kind editor) and
[`README.md`](README.md#game-runs). Scope is deliberately narrow to this tool: **a human designs a
node graph once, saves it in `project.yaml`, and the Run button replays it deterministically
against a live device to auto-play the game** — a macro/bot authoring tool, not a training loop.
Nothing here touches `docs/opengym_implementation_plan.md`'s Gym/RL env; that's a separate,
unrelated consumer of the same wire protocol and shares no code path with this tool.

## 1. Why the current five node kinds aren't enough for a Mario-like run

Action/Delay/Repeat/Compare/Find Template (`GAME_RUN_EDITOR_GUIDE.md` §4) are enough for a fixed,
memorized combo or a single retry loop against one known banner (the worked examples in that
guide's §10). A human trying to script something that actually gets through a level runs into
real gaps:

1. **No data flow between nodes.** Find Template already computes a match position
   (`GameRunExecutor.last_found`, keyed by node id) but nothing routes it into a downstream
   Action's tap coordinates — the guide's own §12 flags this as a known limitation. Without it,
   "find the stairs, then tap where they are" can't be expressed; every Action's coordinates are
   frozen at design time.
2. **Compare/Find are binary, not classifying.** A real level has several obstacle types in play
   (gap, stairs, enemy, pipe, moving platform). Scripting "which of these am I looking at" today
   means a chain of separate Compare nodes tried one after another — no single N-way "what is
   this" switch.
3. **No reusable sub-graphs.** Every recurring maneuver (climb stairs, stomp an enemy, wall-jump)
   has to be rebuilt node-by-node everywhere it recurs. Nothing lets one named Run call another as
   a unit, so nothing composes into a library of obstacle-handling behaviors.
4. **No parameters/variables.** Actions are static event lists baked in at design time. A 3-step
   staircase and a 5-step staircase need two hand-built graphs; nothing lets "jump N times" or
   "tap at (x, y)" be filled in from what was actually detected.
5. **Conditions are checked once, not watched.** Compare/Find fire at one point in the graph.
   There's no "while running right, watch for an enemy and bail out of the current Repeat if one
   shows up" — no way for a condition to race a long-running action/Repeat and preempt it.
6. **No generalized retry/fallback.** The one retry pattern in the guide (§10.B) is hand-wired per
   run; nothing generalizes "this maneuver didn't achieve its expected result, fall back to a
   simpler action."

None of this needs numeric score/OCR extraction (that's the already-scoped, separately-deferred
Phase 2 in `README.md`/`docs/irobot_gym_ide_design.md`) — everything above is about the run
*graph's* expressiveness, orthogonal to reward/score reading.

## 2. Proposed model additions

All additive to `model.py`/`run_engine.py` — existing projects, node kinds, and `project.yaml`
files keep working unchanged, same "additive, not a rewrite" spirit the rest of this codebase's
docs follow.

### 2.1 Variables + coordinate binding (build this first — it unblocks everything else)

Give `GameRunExecutor` a per-run `dict[str, tuple[int, int]]` variable table. `FIND_TEMPLATE`
already computes a position; the only change is naming it (`node.var_name`, defaulting to the
node id) and writing it into that table **as well as** the existing `last_found` — not instead of.
Earlier drafts of this doc left that an open "or" — resolved here because `last_found` is already a
documented contract (`GAME_RUN_EDITOR_GUIDE.md` §4's Find Template section: "other tooling driving
a run programmatically can read back" it); silently dropping it out from under an existing external
reader to make room for the new named table would be a breaking change for zero benefit, when
writing both costs nothing.

Let a `PrimitiveEvent.x`/`y` — and a `RunNode`'s `frames`/`times` — optionally be a variable
reference instead of a literal int, resolved at the moment an Action actually runs:

```yaml
- id: n_tap_step
  kind: action
  action_name: tap_at_found        # an action whose TAP event has x: "$stairs.x", y: "$stairs.y"
```

Smallest possible surface: one new optional string field (`x_var`/`y_var`, or a single
`"$name.x"`-style string parsed at execution time — pick whichever's less invasive once
`model.py`'s dataclass shape is in front of you) alongside the existing literal `x`/`y`. Unresolved
variable (node never fired, or fired down the `not_found` branch) is a run-time error surfaced the
same way an unknown-action/unknown-template is today: log it, skip the event, continue — never
raise, matching every other node handler in `run_engine.py`.

This one change is what makes "detect the stairs, then climb them at the right spot" expressible
at all, by hand or AI-suggested, and is why it should land before anything else in this doc.

**Two things to get right, both consequences of `run_engine.py`'s existing execution model, not new
problems this doc introduces:**

- **Concurrent writes.** `_run_subgraph` already fires forked branches on separate threads
  (`fire()`'s `threading.Thread` calls). A shared, mutable variable table needs the same
  `threading.Lock` `_run_subgraph` already keeps for its `pending`/`active` bookkeeping — cheap to
  add (guard `get`/`set` on the table), easy to silently get wrong if skipped (two parallel Find
  Template nodes writing distinct variable names is safe either way, but a torn read on the *same*
  name from two racing writers is exactly the kind of bug that only shows up intermittently against
  a real device).
- **Staleness across REPEAT iterations.** A variable table is process-wide for the whole run
  invocation — it is **not** reset per REPEAT iteration or per Call-Run. If a body's Find Template
  only fires on some iterations (e.g. behind its own Condition), a downstream reference on a
  skipped iteration reads whatever was written on the *last* iteration that did fire, not an error
  and not "no value yet." Document this plainly in the guide once built (same spirit as
  `run_engine.py`'s own module docstring already documenting the shared-body-node limitation) — an
  author relying on "surely this is fresh this iteration" is the likely failure mode, not a crash.

### 2.1.1 Condition node (`RunNodeKind.CONDITION`) — turning a position into a decision

Raw coordinate binding alone only lets a graph *place* an action; it can't yet choose *which*
action based on what was found — is this a 2-step or a 5-step staircase, is the gap close enough
to hop or does it need a running jump, is the enemy within attack range. A **Condition** node is
Compare's numeric sibling: instead of image similarity, it evaluates one arithmetic comparison over
variables/literals and branches **true**/**false** (two output ports, same if/else spirit as
Compare/Classify — never a fork).

One fused node, not two composed ones — kept consistent with every other node's property panel
being dropdowns/spin boxes rather than free text (Action's action-name dropdown, Compare's
template dropdown, Repeat's iteration spin box): a formula text field would be the first node in
the tab whose mistakes aren't caught by `GameRun.validate()` until run time.

Property panel fields:

- **left**: a variable reference (`$name`, plus an axis picker **x**/**y** when that variable holds
  a point) or a literal integer.
- **op** (optional, default *none*): `+ - * /` against a second operand (same var-or-literal
  shape as `left`) — lets the common "distance/delta" case (`$stairs.x - $player.x`) live in one
  node instead of needing a separate arithmetic step. Leaving `op` at *none* skips straight to the
  comparison, so the node also covers a plain "$lives < 1"-style check with no arithmetic at all,
  once some future numeric-reading node kind exists to populate a variable like `$lives` — not
  designed here, out of scope per §1 (that's the separately-deferred score/OCR Phase 2 in
  `docs/irobot_gym_ide_design.md`).
- **cmp**: `< <= == != >= >`.
- **right**: a third var-or-literal operand, compared against the (possibly arithmetic-combined)
  left side.

Two output ports: **true**, **false**.

**Self-critique worth resolving before this ships**: as specified above, this node has five fields
(left, op, op's second operand, cmp, right) — more than any other node's property panel (Compare has
one: a template dropdown; Repeat has one: an iteration count). That undercuts the very argument used
to reject a free-text formula field in the first place (§2.1.1's opening rationale) — a five-field
structured form isn't obviously easier to read at a glance than the formula it's structurally
equivalent to. Fix: **progressive disclosure, not fewer fields** — the property panel shows only
**left / cmp / right** by default (exactly Compare's one-field simplicity, generalized to three,
which is the common case: a plain threshold check against something Find Template already
produced), with the arithmetic `op` + its operand appearing only once a small "+ arithmetic" toggle
is switched on. The node's canvas label mirrors whichever shape is active (`$x < 100` vs.
`$stairs.x - $player.x < 150`), so the common case stays visually as simple as every other node's,
and the fuller case is opt-in rather than the default footprint.

**Failure modes, handled the same no-surprises way every other node in `run_engine.py` already is
(log and pick a deterministic branch, never raise):** a variable that's a point but has no axis
picked is a static `GameRun.validate()` warning, same table `GAME_RUN_EDITOR_GUIDE.md` §8 already
lists unknown-action/unknown-template warnings in; a variable referenced before anything ever wrote
it (e.g. its Find Template hasn't fired yet, or fired down `not_found`) logs and treats the whole
Condition as **false**; division by zero (`op` is `/`, right-hand operand of the arithmetic step is
0) logs and also treats the Condition as **false** — false is the "safer default" in both cases
since it's the branch that doesn't commit to having found something.

**Where does `$player.x` come from, when nothing in today's model tracks "the player"?** Two
options, both already expressible with existing/proposed pieces, no new node kind needed:

- **Fixed-camera games** (the player sprite stays roughly centered, the world scrolls) — just use a
  literal for the player's screen position; it doesn't change run to run. This covers most 2D
  platformers, including the `mario_platformer.yaml` example's apparent layout.
- **Scrolling/free-camera games** — a second Find Template node against a player-marker template
  (captured once, like any other template, §5 of the guide), whose result binds to `$player` the
  same way `$stairs` does. Condition nodes downstream just reference both variables; no special
  casing needed in the executor.

### 2.2 Call-Run node (`RunNodeKind.CALL_RUN`)

Invokes another named `GameRun` in the same project as a subgraph — the reuse primitive that
turns "climb stairs" into a library entry instead of copy-pasted nodes.

- One input port, one output port (**out**) — behaves like a black-box Action from the outside:
  runs the target Run's full graph to completion (all its own forks/joins), then continues.
- `run_name` property (dropdown of every other Run in the project, same pattern as Action's
  dropdown), plus an optional set of variable bindings (`stairs: $found_stairs`) so the callee's
  own `$stairs.x`/`$stairs.y` references resolve against whatever the caller already found —
  parameter passing, not global variable pollution.
- `run_engine.py`'s `_run_node` gets one more branch: recursively calls `_run_subgraph` against the
  target `GameRun`'s roots with a child variable table seeded from the bindings, same recursion
  shape `REPEAT`'s body already uses. Guard against a Run calling itself (directly or via a cycle
  of Call-Run nodes) with a static check in `GameRun.validate`/a project-wide validator, the same
  place `orphan_releases`-style cross-object checks already live (`model.py`) — this is a simple
  Run-to-Run reachability check over "which Runs does invoking this Run's Call-Run nodes reach,"
  independent of which node/edge kinds sit inside each Run, so it doesn't need to understand
  Condition/Classify edge types at all.

**A real gap this surfaces, not just an implementation detail**: nothing today lets a target Run
*declare* which variables it expects. Without that, the caller's binding UI has no list to populate
(what would "bind `stairs` to `$found_stairs`" even offer as the left-hand side?), and
`GameRun.validate()` has nothing to check a binding against — a missing or misspelled binding would
only surface as a run-time "unknown variable" deep inside the callee, far from the Call-Run node
that actually caused it. Fix: give `GameRun` its own small `params: list[str]` field, declared once
by whoever authors the reusable Run (a small list-editor in that Run's own tab, not the caller's) —
`stairs`, in `climb_stairs`'s case. Call-Run's property panel then offers exactly those names to
bind, and `GameRun.validate()` gets two new checks: a Call-Run binding a name the target doesn't
declare, and a target `params` entry no binding at the call site ever supplies — the same "unknown
reference" shape every other validation warning in this doc already takes. This is, in effect, a
function signature, and is worth naming that way in the guide once built (`params` reads clearer to
an author than a bare unlabeled list).

**Also worth being honest about**: this makes Call-Run's property panel a *dynamic*-length form (one
row per declared param), same complexity category as Classify's dynamic ports (§2.3) — smaller in
practice (most reusable maneuvers need one or two bound positions, not many), but not the flat
one-dropdown simplicity of Action/Compare/Repeat either. Two of the seven proposed/existing node
kinds ending up with dynamic-shaped panels is an acceptable cost for the reuse story, not a reason
to avoid it, but it's the second (and last) node kind in this doc that departs from "fixed small
form" — worth noticing if a third candidate ever shows up, as a signal the model is accreting
complexity rather than composing it.

### 2.3 Classify node (`RunNodeKind.CLASSIFY`) — Compare's N-way sibling

Tests the live frame against a **set** of templates at once (not one) and exposes one output port
per template plus a `none` port for "nothing over threshold" — same if/else spirit as Compare/Find,
generalized to switch/case. **Each template keeps testing its own independently-captured region**
(`ImageTemplate.x/y/width/height`, same as Compare uses today) — a "stairs" template captured at
the bottom-center of the screen and a "monster" template captured wherever monsters tend to appear
are each cropped and compared against their own region, not one shared region reused for every
label. A port's **label is just that template's own `name`** — no separate labeling concept, one
less thing to configure. Internally: run `ImageTemplate.similarity` for every template in the
configured set, take the highest-scoring one that clears *its own* threshold, fire that one port; if
none clear threshold, fire `none`.

Two authors relying on this should keep the label set's templates visually distinct enough that
scores don't sit close together near their thresholds — same threshold-tuning guidance
`GAME_RUN_EDITOR_GUIDE.md` §11 already gives for a single Compare node, just now relevant across a
whole label set instead of one template.

This is the dispatcher a human (or AI, see §3) needs: "if this looks like stairs → Call-Run
`climb_stairs`; if it looks like a pit → Call-Run `long_jump_over_gap`; if it looks like an enemy →
Call-Run `stomp_enemy`; otherwise → keep walking."

**Honest implementation-complexity note**: every other node kind tops out at two named ports
(REPEAT's body/after, COMPARE's match/no_match, FIND_TEMPLATE's found/not_found), fixed at design
time. Classify's port count is **dynamic** — it changes as the property panel's template multi-select
changes (add a fourth obstacle label, get a fourth port) — which is real, new canvas-UI work
(`gui/canvas.py`'s port layout/hit-testing currently assumes a small fixed set per node kind) and
the single largest piece of GUI effort in this whole doc, bigger than the Condition/Call-Run
property panels. Worth prototyping the canvas side early/standalone before committing to it,
precisely because it's the one piece here that isn't "add a property panel field, reuse the
existing port-drawing code."

### 2.4 A race/interrupt primitive — smallest viable version

Full preemption (cancel an in-flight Action mid-send) isn't worth the complexity here — actions are
short and the live device doesn't offer a cancel primitive anyway. What's actually missing is
**polling a condition between iterations of a long Repeat without hand-wiring it into every
iteration**, which is already partially possible today (guide §10.B: wire Compare's `no_match`
back into the loop body) but clunky and easy to get wrong. Proposal: let `REPEAT` optionally take a
third named edge, **`watch`** — a Compare/Find/Classify node checked *before* each iteration
starts (not concurrently, no real threading complexity added); if it fires anything other than the
loop-continuing branch, the Repeat stops early and control passes to whatever `watch`'s fired edge
points at, instead of `after`. Keeps `run_engine.py`'s existing single-threaded-per-branch execution
model intact — no new concurrency primitive, just one more check point `_run_node`'s REPEAT branch
already has a natural place for (right before `self._run_subgraph(game_run, [body_start])` each
iteration).

**Interrupt resolution equals iteration granularity — worth being explicit about, since it drives
how an author should build the body, not just an implementation detail.** A `watch` only gets
checked between iterations, so a body that's one long hold-right Action checked every 60 iterations
of something-else notices an enemy up to that entire body's duration late. An author who actually
wants "watch for an enemy every few frames while running right" needs to author the body as a
*short* per-tick Action (a small step right, re-checked every iteration) rather than one long hold
— a real authoring constraint the guide should state plainly once this ships, not something the
node hides.

**A behavior change worth flagging explicitly, not just an implementation note**: today, a REPEAT
with a connected body always runs it `times` times, full stop — no early exit exists. Once `watch`
is checked before *every* iteration including the first, a REPEAT can now run its body **zero**
times (watch fires immediately). Any author's existing mental model of "body always runs at least
once if `times >= 1`" quietly stops holding the moment they wire up a `watch` edge — worth a
one-line callout in the guide's node-types table, not just left implicit in the execution order.

**A positive finding worth stating plainly, not burying**: with `watch` in place, REPEAT already
*is* a while-loop — set `times` to something arbitrarily large (the guide's own §10.B worked example
already does exactly this, `times: 9999`, specifically because no real while-loop existed yet) and
let `watch` do the actual stopping. This doc does **not** need a separate "loop until condition" node
kind — that would just be REPEAT with different words on the same two knobs (a bound and a stop
check) it already has once §2.4 ships. One less node kind than a naive reading of "we need a
while-loop" would suggest.

### 2.5 Fallback edge convention (no new node kind needed)

**Correction from an earlier draft of this doc**: Call-Run stays single-port (§2.2) — no
success/fail ports on the *call* itself. Baking "did it work" into the callee doesn't actually fit
a single-port node without inventing a new return-value mechanism (a `Return` pseudo-node, an
implicit result variable) that this doc otherwise has no need for, and different call sites often
want different definitions of "success" for the same maneuver anyway (climbing stairs mid-level
vs. climbing the same stairs while being chased means checking different post-conditions).

So the post-condition check is the **caller's** responsibility, not the callee's: wire a
Compare/Find/Condition node directly after the Call-Run node in the *calling* graph, checking
whatever live state indicates the maneuver actually worked, then branch from there to a retry or a
fallback. This is exactly `GAME_RUN_EDITOR_GUIDE.md` §10.B's existing retry pattern — Call-Run just
means the body being retried is a reusable library entry instead of a copy-pasted subgraph. No
schema change; a documented authoring pattern, covered in the guide once §2.2 ships.

### 2.6 Node-kind count: merges considered and rejected

Seven kinds after this doc (ACTION, DELAY, REPEAT, COMPARE, FIND_TEMPLATE, CONDITION, CALL_RUN,
CLASSIFY — §2.4's `watch` is an edge, not a node, per §2.4's positive finding above). Worth
explicitly checking whether any of these should collapse into another before locking the schema in,
rather than letting the count grow by inertia:

- **COMPARE + CLASSIFY → one node, N templates where N=1 is today's Compare.** Genuinely
  considered: it would cut a node kind and share `_run_compare`-shaped code entirely. Rejected for
  UX, not implementation cost — a node kind whose port count silently changes shape (fixed
  match/no_match at N=1, dynamic N+1 ports at N>1) is a worse reading experience on the canvas than
  two distinctly-colored kinds with fixed, predictable meanings, and this codebase already spends a
  color per kind specifically so a glance at the canvas tells you what a node does. Keep them
  separate at the schema/GUI level; share the underlying `ImageTemplate.similarity` comparison code
  between their two `run_engine.py` handlers so the *logic* isn't duplicated even though the *node
  kinds* are.
- **FIND_TEMPLATE + CLASSIFY → one configurable node** (toggle full-frame-search vs. fixed-region,
  toggle single-template vs. label-set, toggle position-output vs. label-output). Rejected harder
  than the above: that's a 2×2×2-ish configuration space collapsed into one property panel, which is
  exactly the "premature abstraction" this codebase's own conventions warn against elsewhere — two
  clear single-purpose node kinds (locate vs. identify) beat one node with three toggles that's
  simple in no configuration.
- **DELAY as a redundant special case of ACTION** (a one-event WAIT-only action does the same
  thing) — noted, not fixed: technically true, but DELAY's whole value is *not* having to pre-declare
  a named action for every distinct pause a graph needs. Correctly kept as-is; flagging it here only
  because "review all node types" should include the ones nobody proposed changing, not just the new
  ones.

Net: this doc adds three real node kinds (CONDITION, CALL_RUN, CLASSIFY) plus one edge (`watch`) to
the existing five, and every merge that would have reduced that count further was rejected for a
concrete, stated reason above rather than left unconsidered.

## 3. AI-assist: design-time co-author, never a runtime controller

**Key call:** keep AI out of the live control loop. A vision-model round-trip is tens to hundreds
of milliseconds slower than a platformer's jump-timing tolerance, and it makes replays
non-reproducible — the opposite of what this tool is for (author once, replay deterministically).
So AI's job is to **help build the node graph**, not to run alongside it.

### 3.1 The natural pipeline, reusing what already exists

`device_recorder.py` already captures a human's real touches on the physical device via
`adb shell getevent` and turns them into a single Action (`GAME_RUN_EDITOR_GUIDE.md`'s sibling doc,
`README.md` §"Record from Device"). That's the input an AI-assist step needs, with two additions:

1. **Capture a labeled demo, not just an action.** Human clicks "Record from Device," plays through
   one instance of the maneuver for real (climbs one staircase), stops, and names the *situation*
   ("climbing 3-step stairs") rather than only the resulting action — same recording plumbing,
   one more prompt.
2. **AI segmentation, offered as a suggestion, not applied automatically.** Feed the recorded raw
   event trace plus the before/after frames (already available: `LiveConnection.latest_frame()` at
   record-start/record-stop) to a vision-capable model with a prompt naming the maneuver. Ask it to
   propose a **parameterized node subgraph** — e.g. `N × [tap jump, wait, move right]` where `N` is
   read off the *step count* found by a Find Template/Classify node the AI also proposes pointed at
   a stair-tread template — using this doc's §2.1 variable syntax so the proposal is expressed in
   the exact same schema a human would hand-author.
3. **Human review before it's saved.** The GUI shows the proposed nodes/edges overlaid on the
   canvas (same visual language as everything else in the tab) for the human to edit, rename, or
   discard — never auto-committed to `project.yaml`. This matches every other AI-assisted authoring
   pattern (Copilot-style suggestion, not autonomous edit) and sidesteps the reliability question
   entirely: a wrong AI suggestion costs a rejected diff, not a broken live run.
4. **Saved as a named Run, invoked via Call-Run (§2.2).** Once accepted, "climb_stairs" becomes a
   library entry like any hand-built one — reusable from a Classify node's `stairs` branch anywhere
   in the project, and across projects if `project.yaml`'s Runs are ever given an import/copy
   mechanism (not designed here — out of scope until a second project actually wants to share one).

### 3.2 Reliability: pair every AI-authored Call-Run site with a post-condition check

Per §2.5's (corrected) convention, the check belongs at the **call site**, not inside the
AI-generated Run itself: whatever graph invokes an AI-authored "climb_stairs" via Call-Run should
immediately follow it with a Compare/Find/Condition node checking an expected post-state (player
cleared the top of the stairs), branching to a retry or a fallback (a safer hand-authored default —
jump repeatedly and hope) rather than stalling the whole run. Since an AI-suggested subgraph is
reviewed before saving (§3.1 step 3), the reviewing human should treat "does this call site have a
post-check wired after it" as part of what they're approving, same as reviewing the subgraph's
actions themselves — this is the one piece of scaffolding that keeps an imperfect AI suggestion
from silently derailing an otherwise long, unattended playthrough.

### 3.3 What this explicitly does *not* propose

- **No live LLM-in-the-loop node** ("ask AI what to do right now, given this frame") — rejected per
  the latency/reproducibility argument above. If a future need for this shows up, it belongs behind
  a very clearly-labeled node kind with its own timeout/fallback semantics, not folded into today's
  deterministic executor.
- **No automatic template/obstacle discovery** (AI scanning a level for "things that look like
  hazards" unprompted) — templates stay human-captured (`GAME_RUN_EDITOR_GUIDE.md` §5); AI only
  helps turn an already-captured situation into a subgraph.

### 3.4 A second entry point: point-to-point planning as an MCP tool

§3.1's demo-recording pipeline is the right tool when a maneuver's exact motion is easier to
*demonstrate* than to specify from two static points (a wall-jump's precise timing). A lot of
level-specific goals are the opposite shape: **the start and goal positions are already known,
fixed, at design time** ("walk from spawn to the first platform's edge"), and no physical
play-through is needed to produce a plan for them — this is the common case, in fact, given this
whole tool's premise of a deterministic, repeatable playthrough of the same level layout.

Expose this as an MCP tool — `design_action_sequence` — rather than a bespoke in-app AI call, so
any MCP-capable client (a "AI Suggest" button inside this GUI, or a coding agent/session working on
the project directly) can invoke it the same way:

```
Tool: design_action_sequence

Input:
  reference_resolution: {width, height}
  start: {x, y}                              # player's position
  goal:  {x, y}                              # e.g. a Find Template result captured once at design time
  frame_image_b64: <captured/live frame>      # for terrain reasoning -- see below for why this matters
  available_actions: [{name, description}, ...]   # project.actions, reusing Action.description
  frame_ms: 33                                 # FRAME_MS, so wait_frames reasoning is grounded in real time

Output (a GameRun fragment -- same schema project.yaml already uses):
  nodes: [{id, kind: action|delay, action_name | frames}, ...]
  edges: [{id, source, target}]              # a sequential chain, via defaults to "out"
  notes: "there's a gap around x=550-700; inserted long_jump to clear it"
```

Two things make this worth building as an MCP tool rather than a plain function call:

- **`available_actions` reuses `Action.description`** (`model.py`), a field that exists today and
  goes unused by everything else in this tool — this is exactly what it's for.
- **The frame image is what actually earns the "AI" label.** `start`/`goal` coordinates alone barely
  need a model — that's `dx`/`dy` and a move count, no smarter than §3.5's control loop below. The
  tool is worth calling specifically because it can *see* the terrain between the two points and
  reason about it — "there's a gap here, insert `long_jump` instead of walking off the edge" — which
  a pure-arithmetic function can't do.

**Consumption, reusing existing code, not new trust machinery:** load the response with
`GameRun.from_dict()` and run the existing `GameRun.validate()` against it *before* showing it to
the human — a hallucinated action name gets caught by the exact same check that already flags a
hand-authored typo today. Overlay it on the canvas for review (same UI as §3.1 step 3); on
acceptance, save it as a named Run, reusable from a Call-Run node anywhere it's needed.

**Limitation worth being explicit about**: this produces one fixed sequence for one specific
`(start, goal)` pair — not a generalized policy that adapts to wherever a target happens to land at
run time. That's the dividing line with §3.5 below, not a shortcoming to fix.

**Safety note, not a new mechanism — validation already covers it**: `GameRun.validate()` only
checks *referential* integrity (does `action_name` exist), not *semantic* safety — a proposed
sequence that happens to reuse a real, validly-named action in a spot the human didn't intend it
(same category of risk `docs/opengym_implementation_plan.md` §13 already flags for a trained agent's
action space: "an untrained agent tapping randomly can hit an ad's outbound link or an in-app
purchase button"). Human review before saving (this section's own requirement) is what actually
covers this here — worth the reviewer specifically eyeballing *which* actions got chosen, not just
that the graph loads and validates cleanly.

### 3.5 When to use which: one fixed pair vs. many varying instances

Two genuinely different tools for two genuinely different situations, both landing in this doc:

- **§3.4's point-to-point planning** — the start/goal are fixed and known once, at authoring time,
  for one particular spot in one particular level ("the gap right after spawn"). Call it once,
  review the plan, save it, done — it never needs to be recomputed.
- **A reactive Condition-loop** — built from §2.1.1's Condition node plus Find Template plus Repeat
  plus a `watch` edge (§2.4) — for a maneuver that recurs many times against *varying* positions
  within one run (five similarly-shaped treasure boxes scattered at different x-coordinates through
  a level): re-find both positions every iteration, branch on the sign/magnitude of the delta, take
  one step, repeat, terminate once the target's template stops matching. No AI involved at all —
  this is a small, fully deterministic feedback loop, and it's the better fit specifically because
  it generalizes across positions the fixed §3.4 plan doesn't need to (and can't) adapt to.

Don't reach for either when a straight Compare-then-Action macro already covers it (§1's original
worked example: a fixed-shape obstacle at a roughly fixed screen position needs neither).

## 4. Suggested build order

1. **§2.1 Variables + coordinate binding.** Smallest change, and a prerequisite for §2.1.1 and
   §2.2–§2.4 and all of §3 — do this first, independent of everything else.
2. **§2.1.1 Condition node.** Depends only on step 1's variable table; turns a found position into
   a branch. Do this right after variables, before Call-Run/Classify — it's what makes a single
   hand-built obstacle handler (no library yet) already useful for variable-shaped obstacles.
3. **§2.2 Call-Run node, including `GameRun.params`.** Unblocks a hand-built obstacle library,
   reusing Condition nodes inside each library entry — validate the reuse story works for a human
   first, before any AI involvement. Land `params` alongside the node itself, not as a follow-up —
   without it there's no binding UI and no way for `validate()` to catch a mis-wired call.
4. **§2.3 Classify node.** The dispatcher that makes a library of Call-Run targets actually useful
   in a real run instead of a pile of unreferenced Runs.
5. **§2.4 Repeat's `watch` edge.** Smaller, independent; do whenever a real authored run needs it.
6. **§3's AI-assist workflow.** Depends on 1–4 existing so its output has somewhere useful to go;
   start with the human-in-the-loop review UI (a static "here's what recording+AI produced, edit
   before saving" panel) before considering any automation of the review step itself. §3.4's MCP
   tool can land before or after §3.1's demo-recording pipeline — they share the same review UI and
   the same output schema (a `GameRun` fragment), so building the review UI once serves both; §3.4
   is arguably the cheaper of the two to stand up first (no `device_recorder.py` plumbing needed,
   just the tool call + existing `GameRun.validate()`).

Each step is independently mergeable and testable against the existing pure-Python test suite
(`irobot_gym_ide/tests/`) the same way `model.py`'s existing node kinds are — no device required for
the schema/executor logic, same split the current tests already use (`test_model.py` for validation,
a `run_engine`-level test with a fake `LiveConnection` for execution).
