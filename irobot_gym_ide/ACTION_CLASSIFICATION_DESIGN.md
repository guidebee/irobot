# Action definitions & classification — design and a punch list of gaps

Status: **implemented** (`model.py`, `hud_classifier.py`, `gui/main_window.py`'s `_classify_session`).
This doc records the design as built, the reasoning behind it, and a prioritized list of gaps to
close next — companion to [`GAME_RUN_AI_ASSIST_DESIGN.md`](GAME_RUN_AI_ASSIST_DESIGN.md) (which
covers authoring a `GameRun` node graph) and [`GAME_RUN_EDITOR_GUIDE.md`](GAME_RUN_EDITOR_GUIDE.md)
— both of those assume a decent `Action` library already exists. This doc is about how that library
actually gets built and refined in the first place, since neither hand-authoring every action nor a
one-shot recording gets there: real HUD layouts need an iterative bootstrap.

Each gap in §3 gets its own status line, flipped from **open** to **Fixed (see commit/PR)** as it's
implemented — that's the "update the design doc as we go" half of this doc's purpose, not just a
one-time review.

## 1. The pipeline as built

1. **Record** a whole playthrough as a raw `GameplaySession` (Sessions tab → "Record Gameplay
   Session") — a flat, chronological stream of `PrimitiveEvent`s (model.py), independent of any one
   named `Action`.
2. **Classify** it (`hud_classifier.classify_session`, wired to the "Classify Session" button). Every
   gesture in the stream (a `TAP`, or a `PRESS`...`RELEASE` pair on one pointer) is checked in order
   against, in priority order:
   1. The project's `HudRegion`s — a plain point-in-rectangle test against the gesture's *start*
      point, smallest-area region wins ties (`_best_region`). This is the primary, authored signal:
      a human deliberately drew this rectangle over this button.
   2. Failing that, the project's existing `Action`s, via pattern-matching the gesture's own raw
      events against each action's own recorded events (`model.find_matching_action`, backed by
      `model.events_look_alike` — WAIT-agnostic, position-tolerant equality). A hold gesture (real
      PRESS...RELEASE span) that doesn't match any single action whole gets one more try as a
      bookend pair — its press half checked against every action, its release half checked
      independently — so it can still resolve against two separately-recorded `_start`/`_stop`
      actions even with no HudRegion covering that spot at all.
   3. Two or more regions touched at overlapping times fold into one segment naming a
      `HudRegionCombo`'s action, but *only* when the exact set of touched region names matches a
      combo an author explicitly declared — an unmatched concurrent cluster falls back to
      classifying each region separately (1 and 2 above), never guessed at.
   A `HudRegion` marked as a hold control (`release_action_name` set, `HudRegion.is_hold`) always
   produces two bookend `SessionSegment`s — one at the press index naming the "start" action, one at
   the release index naming the "stop" action — instead of one segment spanning the whole hold, so
   `session_replay.py`'s "Replay Classified" reproduces the *real* recorded hold duration instead of
   running one fixed-length canned action.
3. **Propose actions** (`hud_classifier.propose_actions`) for the two gaps classification alone
   leaves: a segment naming an action that isn't a real project `Action` yet (built from that
   segment's own recorded event slice), and a gesture that matched neither a region nor an existing
   action at all (named `unknown_1`, `unknown_2`, ... — never colliding with an existing name or an
   earlier placeholder from the same call — also built from its own recorded slice). A name
   collision with an existing action is skipped outright, never overwritten. A *new* name whose
   events merely *look like* a differently-named existing action gets a `"possible duplicate of
   'X'"` hint appended to its description instead of being silently dropped — a human decides
   whether that's really the same button recorded twice.
4. **Human review.** A Yes/No dialog lists every proposal (calling out which are flagged as
   possible duplicates) before anything is added to `project.actions`. Once added, the human
   renames/edits/deletes them in the Action Inspector as needed, then explicitly saves the project —
   nothing here auto-saves to disk.
5. **Iterate.** Record another session, or re-classify the same one, now against the enlarged
   action/region library. Gestures that were `unknown_N` last round, or that matched a rough/stale
   action, get a chance to resolve better as the library grows. Repeat until the user is satisfied —
   today, that's judged informally by "no more unknown segments," see G2 below for why that's not
   quite the same as "fully correct."

## 2. Design rationale

- **No ML, deliberately.** A touchscreen hands you exact, discrete DOWN/MOVE/UP events with exact
  timestamps and coordinates — there's no genuine segmentation ambiguity for a learned model to
  resolve (contrast with audio-to-text, where even the unit boundaries are uncertain and *must* be
  inferred statistically). What's left is a lookup (which region/action does this point/sequence
  belong to) and an exact-set combo rule, both fully explainable and reproducible from the raw
  stream plus the project's own definitions.
- **Propose, don't apply.** Same human-review-before-anything-is-saved precedent
  `GAME_RUN_AI_ASSIST_DESIGN.md` §3 already establishes for AI-suggested `GameRun` subgraphs:
  `classify_session` never mutates the session, `propose_actions` never mutates the project — both
  return data for a caller (the GUI, here) to act on only after a human says yes.
- **Hold regions bookend rather than span.** Splitting a held control into a `PRESS`-only "start"
  action and a `RELEASE`-only "stop" action mirrors how Android itself delivers a held touch (one
  DOWN, silence while held, one UP — no repeat needed) and lets an agent (or a human) hold a
  direction for an arbitrary, variable duration instead of a fixed number of recorded frames.
  Classification reproduces that same split as two bookend segments so replay honors the real held
  duration, not a canned macro's baked-in wait count.
- **HUD region match always outranks pattern match.** An explicit, authored rectangle is a stronger
  signal than "this raw event sequence resembles that one" — pattern-matching is the fallback for
  wherever the human hasn't (yet) drawn a region, not a competing primary signal.
- **Growing the action library is itself the improvement mechanism.** There's no separate "training"
  step — every accepted proposal directly becomes a new pattern the *next* classification pass can
  match against, even at a screen location no `HudRegion` covers. This is what makes the iterate step
  in §1.5 actually converge over successive rounds rather than repeat the same gaps forever.

## 3. Known gaps — prioritized punch list

### High priority — correctness/safety

**G1. Renaming an action doesn't cascade.** *(status: open)*
`HudRegion.action_name`/`release_action_name`, `HudRegionCombo.action_name`, and
`RunNode.action_name` are all plain strings naming an action — nothing updates them when a human
renames an action in the Inspector. A fresh `unknown_N` proposal is safe to rename (nothing points at
it yet), but renaming an action a `HudRegion` *already* references (e.g. `jump_button.action_name ==
"jump"`, human renames `"jump"` to `"jump_v2"`) silently orphans that region. Worse, the *next*
classify+propose cycle sees `HudRegion.action_name == "jump"` still doesn't exist as a real action
and proposes a brand-new `"jump"` action from whatever gesture happens to land there next — quietly
re-creating the exact thing the human tried to rename away from. This is the one gap that can
actively fight the §1.5 iterate loop instead of just leaving something imperfect.
*Fix direction:* a dedicated "rename action" operation (not free-text edit of the name field) that
finds and updates every `HudRegion`/`HudRegionCombo`/`RunNode` reference project-wide, same spirit as
an IDE's "rename symbol" refactor.

**G2. "Zero unknown" measures coverage, not correctness.** *(status: open)*
A gesture can pattern-match the *wrong* existing action (tolerance-based, not exact) and the loop
will call that "resolved." There's currently no visibility into *which* segments were matched by
fuzzy pattern-matching vs. a crisp HUD region, even though that distinction is already sitting
unused in `SessionSegment.label` (`"pattern:<name>"` vs. the region's own name).
*Fix direction:* surface that distinction in the classify-session log/GUI so a human spot-checks
pattern-matched segments at least once, not just the outright unknowns.

**G3. `find_matching_action` is first-match, not best-match.** *(status: open)*
It returns the first action in dict order within tolerance, not the closest one. As the library
"gradually improves" and grows, the odds of two near-duplicate actions both being in range of a new
gesture go *up*, not down — this failure mode gets more likely precisely as the process succeeds,
which is a nasty property for something meant to converge.
*Fix direction:* pick the nearest candidate (minimum position delta) instead of the first; log when
more than one candidate qualifies within tolerance so a human notices the library is getting
crowded in that spot.

### Medium priority — workflow ergonomics

**G4. No diff view when reclassifying.** *(status: open)*
Today, re-classifying a session with existing segments is a blunt "overwrite them, yes/no?" The
whole point of the iterate step is seeing *what improved* after growing the library — a before/after
summary (N segments unchanged, M previously-unknown gestures now resolved, K segments reclassified
differently) would make that legible instead of a blind overwrite.

**G5. No `propose_combos` sibling.** *(status: open)*
A single unmatched gesture auto-proposes as `unknown_N`. A recurring *combo* (two regions touched
concurrently with no matching `HudRegionCombo`) only produces a log warning
(`"...have no matching HudRegionCombo -- classified separately"`) — there's no automatic-suggestion
path analogous to `propose_actions` for combos. Any game leaning on simultaneous-touch actions gets
half the bootstrap convenience the single-button case gets.

**G6. `unknown_N` proposals carry no positional/visual context.** *(status: open)*
No coordinates in the log line or description, no frame thumbnail — reviewing a batch of
`unknown_7`..`unknown_12` means opening each in the Inspector and reverse-engineering what it was
from raw (x, y) alone. Cheapest fix: put the coordinates in the description/log line. A frame
thumbnail (recording sessions already have access to `LiveConnection.latest_frame()` per
`GAME_RUN_AI_ASSIST_DESIGN.md` §3.1) would be a further, pricier improvement.

### Low priority — inherent limitations to decide on explicitly, not silently hope away

**G7. Drag/analog gestures may never reach "zero unknown."** *(status: open, decision needed)*
`events_look_alike` requires equal non-WAIT event counts; two recordings of the same swipe/drag
almost never sample to the same length, so they'll essentially never pattern-match each other. Any
game with joystick/aim-drag controls should not expect "classify until zero unknown" to be a
reachable goal for those gestures specifically — worth deciding up front whether that's an accepted
permanent exception (e.g. only tap/hold-style gestures are expected to fully converge; drags stay
manually labeled or get a separate simplification/resampling step) rather than discovering it
mid-project.

**G8. `position_tolerance_px` is a hardcoded constant (default 30), not exposed anywhere.**
*(status: open)* Fine for one screen density/button spacing, potentially wrong for a cramped HUD with
small adjacent buttons (too loose → false matches) or a sparse one (too tight → real repeats with
finger jitter fail to match). No project-level setting or per-region override exists yet.

**G9. Pattern-matching is O(gestures × actions).** *(status: open, no action needed yet)*
Fine at today's scale (a HUD-driven game's action library — tens, not thousands). Worth remembering
if this pipeline is later run over large recorded corpora for behavior-cloning-style dataset
generation rather than one-off IDE sessions, per the stated eventual Gym/Game-Run consumers of this
library.

## 4. Suggested build order

1. **G1** (rename cascade) — do this first; it's the one gap that can actively corrupt the iterate
   loop the rest of this doc's process depends on.
2. **G3** (nearest-match, not first-match) — small, and directly improves match quality as the
   library grows, which is the process's core selling point.
3. **G2** (surface pattern-matched segments distinctly) — small logging/labeling change, big trust
   improvement for the "verify" half of the loop.
4. **G6** (coordinates in unknown proposals) — cheap, do anytime, no dependencies.
5. **G4** (diff view on reclassify) — moderate GUI work, biggest ergonomics win for repeated
   iteration.
6. **G5** (`propose_combos`) — closes the combo-side asymmetry once the single-region path (G1–G4)
   is solid.
7. **G7/G8** — not code changes so much as decisions to make explicit and (for G8) a config surface
   to add once a real project hits the limitation.
8. **G9** — only if/when session corpora actually get large enough for it to matter.

Each step above is independently mergeable and testable against the existing pure-Python suite
(`irobot_gym_ide/tests/test_model.py`, `test_hud_classifier.py`) the same way the rest of this
codebase's model-level logic is — no device required.
