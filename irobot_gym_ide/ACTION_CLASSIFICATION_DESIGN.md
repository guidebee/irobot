# Action definitions & classification — design and a punch list of gaps

Status: **implemented, including the G1–G6/G8 punch-list fixes below** (`model.py`,
`hud_classifier.py`, `gui/main_window.py`'s `_classify_session`, `gui/panels/library_panel.py`,
`gui/panels/sessions_panel.py`).
This doc records the design as built, the reasoning behind it, and a prioritized list of gaps to
close next — companion to [`GAME_RUN_AI_ASSIST_DESIGN.md`](GAME_RUN_AI_ASSIST_DESIGN.md) (which
covers authoring a `GameRun` node graph) and [`GAME_RUN_EDITOR_GUIDE.md`](GAME_RUN_EDITOR_GUIDE.md)
— both of those assume a decent `Action` library already exists. This doc is about how that library
actually gets built and refined in the first place, since neither hand-authoring every action nor a
one-shot recording gets there: real HUD layouts need an iterative bootstrap.

Each gap in §3 gets its own status line, flipped from **open** to **Fixed** as it's implemented —
that's the "update the design doc as we go" half of this doc's purpose, not just a one-time review.
**Update:** G1–G6, G8, and G10 are now implemented (G1-G6/G8 all in one pass rather than the
originally-planned incremental order, per the build order in §4; G10 discovered separately via
real user testing after that pass shipped -- see each gap's status line below for exactly what
landed and where its tests live); G7 is a recorded decision, not a code change; G9 remains
genuinely open, to revisit only if it ever matters at real scale.

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

**G1. Renaming an action doesn't cascade.** *(status: Fixed)*
`HudRegion.action_name`/`release_action_name`, `HudRegionCombo.action_name`, and
`RunNode.action_name` are all plain strings naming an action — nothing updated them when a human
renamed an action in the Inspector. Fixed with `Project.rename_action(old_name, new_name)` (model.py):
renames the `actions` dict key and the `Action`'s own `.name`, then cascades to every
`HudRegion.action_name`/`release_action_name`, `HudRegionCombo.action_name`, and
`RunNode.action_name` reference across every `GameRun` in the project, returning the number of
references updated. Raises `KeyError`/`ValueError` for a missing/colliding name rather than silently
doing the wrong thing. The Library dock's Rename button (`gui/panels/library_panel.py`'s
`renameRequested` signal, `_RENAMABLE_CATEGORIES`) drives this instead of a bare free-text name edit
(there was no rename UI at all before this). `Project.rename_hud_region` gets the same treatment for
HUD region names (cascading into `HudRegionCombo.region_names`), since a region rename can orphan a
combo the same way an action rename could orphan a region/combo/run. Tests:
`ProjectRenameActionTest`/`ProjectRenameHudRegionTest` in `test_model.py`.

**G2. "Zero unknown" measures coverage, not correctness.** *(status: Fixed)*
A gesture can pattern-match the *wrong* existing action (tolerance-based, not exact) and the loop
will call that "resolved," with no visibility into *which* segments were matched by fuzzy
pattern-matching vs. a crisp HUD region. Fixed: `classify_session`'s summary log line now breaks the
matched count down by *how* each gesture matched -- `"N via HUD region, M via HUD combo, K via
existing-action pattern"` -- so a human can tell at a glance how much of a session's classification
rests on the fuzzier signal and is worth a second look, not just the outright-unmatched count.
`SessionSegment.label` already carried the `"pattern:<name>"` marker this reads from.

**G3. `find_matching_action` was first-match, not best-match.** *(status: Fixed)*
It returned the first action in dict order within tolerance, not the closest one -- a failure mode
that gets more likely precisely as the library grows, which is a nasty property for something meant
to converge. Fixed: `model.find_matching_action` now ranks every within-tolerance candidate by
summed position distance (`model._events_match_distance`) and returns the nearest; an optional
`on_ambiguous` callback is invoked with every qualifying candidate name (nearest first) whenever more
than one qualifies, so a caller can log it. Wired into both `classify_session` (logs a "Note: gesture
matched N existing actions..." line) and `propose_actions`' duplicate-flagging (`_flag_if_duplicate`).
Tests: `FindMatchingActionTest` in `test_model.py`, `PatternMatchAmbiguityTest` in
`test_hud_classifier.py`.

### Medium priority — workflow ergonomics

**G4. No diff view when reclassifying.** *(status: Fixed)*
Re-classifying a session with existing segments used to be a blunt "overwrite them, yes/no?" Fixed
with `hud_classifier.diff_classifications(old_segments, new_segments)` -- a pure function keyed by
`(start_index, end_index)` span returning `{unchanged, changed, added, removed}` counts -- computed
in `gui/main_window.py`'s `_classify_session` *before* asking to overwrite, so the confirmation
dialog shows what a fresh classification would actually change (e.g. "3 newly classified, 1 changed
to a different action") instead of a blind overwrite prompt. Tests: `DiffClassificationsTest` in
`test_hud_classifier.py`.

**G5. No `propose_combos` sibling.** *(status: Fixed)*
A single unmatched gesture auto-proposed as `unknown_N`; a recurring *combo* (two regions touched
concurrently with no matching `HudRegionCombo`) only produced a log warning, with no
automatic-suggestion path analogous to `propose_actions`. Fixed with
`hud_classifier.propose_combos(session, regions, combos)`: finds every concurrent-region cluster with
no matching combo, proposes one new `HudRegionCombo` per distinct region-name set (named by joining
the region names, e.g. `"jump_button+right_button"`). Accepting a proposal doesn't itself create the
backing Action -- the *next* classify_session run folds the cluster into one segment naming the
combo's `action_name`, and `propose_actions` then proposes that action from the cluster's own raw
events, same as any other not-yet-real action name; deliberately reuses that existing machinery
rather than duplicating it. Wired into `_classify_session` with its own accept/decline dialog, after
the action-proposal step. Tests: `ProposeCombosTest` in `test_hud_classifier.py`.

**G6. `unknown_N` proposals carried no positional/visual context.** *(status: partially Fixed)*
No coordinates in the log line or description, no frame thumbnail. Fixed the cheap half: both
`propose_actions`' classified-name proposals and its `unknown_N` placeholders now include the
gesture's own `(x, y)` in the description and the log line (`_location` helper in
`hud_classifier.py`). The frame-thumbnail half (recording sessions already have access to
`LiveConnection.latest_frame()` per `GAME_RUN_AI_ASSIST_DESIGN.md` §3.1) is real GUI/capture work and
remains undone -- left as a follow-up if coordinates alone turn out not to be enough context in
practice. Tests: coordinate-inclusion cases in `ProposeActionsTest`, `test_hud_classifier.py`.

**G10. A HUD Combo can silently make "Replay Classified" much shorter than "Replay Raw."**
*(status: Fixed -- discovered after G1-G9 shipped, via real user testing)*
Classification correctly *names* every segment, but nothing checked whether a segment's action
*timing* bears any resemblance to how long that segment's real gesture actually took to record.
Concretely: `examples/mario_platformer`'s `right_jump`/`left_jump` `HudRegionCombo`s (added
in an earlier pass of this doc's own work) fold a whole "hold right while mashing jump" span into
one segment naming the `right_jump` action -- correct as a *label*, very wrong as a *replay*,
since that action's own canned macro only waits ~6 frames while the real recorded span was 284-339
frames. Measured on `recordings/level2.session.yaml`: Replay Raw's scripted total is 880 frames;
with the combo, Replay Classified's was only 237; without it, 877 (i.e. matching). The
HudRegionCombo mechanism is a good fit for a short, discrete, one-shot compound gesture (a quick
nudge + jump) but an actively harmful fit for "hold indefinitely while repeating something," which
is just ordinary sustained gameplay, not a special move.
*Fix:* removed the `right_jump`/`left_jump` combos from `hud.yaml` (the underlying
`right_jump`/`left_jump` *Actions* are untouched and still usable directly, e.g. from a Game Run
node) so that overlap now classifies as separate `right_start`/`jump`/`right_stop` segments, which
correctly bookend the real hold duration; re-classified and re-saved `level2.session.yaml` to
match. Also added `hud_classifier.compare_replay_durations(session, project_actions)` -- computes
Replay Raw's scripted total, what Replay Classified would actually take, and a per-segment
mismatch list (recorded span duration vs. that segment's action's own WAIT total) -- wired into
`_classify_session`'s log output so this class of issue surfaces automatically at classify-time
for any project, not just this one, and not only after a human notices a replay feels off. Tests:
`CompareReplayDurationsTest` in `test_hud_classifier.py`.

**G10 addendum: replay-time self-correction, using Replay Raw as the ground truth.** *(status: Fixed)*
Removing the bad combo fixes *this* project's data, but the underlying gap (an action's own
canned timing can diverge from what a specific occurrence actually took) is structural, not
specific to one HudRegionCombo -- any reused action will drift from *this* recording's real
timing to some degree. Since Replay Raw is, by construction, the exact recorded stream, it's the
natural ground truth to reconcile Replay Classified against directly, rather than only
diagnosing the gap at classify-time. Fixed: `session_replay.SessionPlayer.replay_classified` now
tops up with a "catch-up" sleep after running each segment's action, for the difference between
that segment's real recorded span (`model.frames_between` over `[start_index, end_index)`) and
the action's own WAIT total -- logged as `"(+N frame(s) catch-up...)"`. `hud_classifier.
build_game_run` got the same treatment: passing `project_actions` now appends an extra DELAY
node after an ACTION node whenever its segment's real span exceeds the action's own timing, so a
built Game Run graph paces the same way under `run_engine.py`.

**The guarantee this gives, precisely stated, since it's asymmetric by design:** catch-up only
tops up, never trims -- there's no way to un-spend time an action's own script already took
sending real touch events, so Replay Classified's total can no longer come out *shorter* than
Replay Raw's, but it can still come out *slightly longer* in aggregate for a session with many
quick, reused actions whose own canned timing individually exceeds some occurrences' real
duration (each such occurrence still pays that action's full fixed cost; only the segments where
the reverse was true get topped up). Measured on `recordings/level2.session.yaml`: raw is 880
frames; classified was 877 without catch-up (this project's own numbers happened to roughly
balance out) and 985 with it -- worse in this one aggregate-total sense, but for the right
reason: it's no longer possible for a future combo/action mismatch to silently produce a
237-frame-style collapse without at least being bounded below by the real recording. Solves the
reported symptom ("classified replay feels too short") directly rather than only diagnosing it.
Tests: catch-up cases in `test_session_replay.py`'s `ReplayClassifiedTest` and
`test_hud_classifier.py`'s `BuildGameRunTest`.

### Low priority — inherent limitations to decide on explicitly, not silently hope away

**G7. Drag/analog gestures may never reach "zero unknown."** *(status: decision recorded, no code change)*
`events_look_alike`/`_events_match_distance` require equal non-WAIT event counts; two recordings of
the same swipe/drag almost never sample to the same length, so they'll essentially never
pattern-match each other. Decision: this is an **accepted permanent exception**, not a bug to chase --
"classify until zero unknown" is a realistic convergence target only for tap/hold-style gestures.
A game with joystick/aim-drag controls should expect those specific gestures to stay manually
labeled (or get a dedicated simplification/resampling step, not designed here) rather than trying to
drive their unknown count to zero through this pipeline.

**G8. `position_tolerance_px` was a hardcoded constant, not exposed anywhere.** *(status: Fixed)*
Fine for one screen density/button spacing, wrong for others, with no project-level setting. Fixed:
`Project.action_match_tolerance_px` (default 30, persisted in `project.yaml` via `io.py`'s
`_META_KEYS`) is now the single source of truth, threaded through every `classify_session`/
`propose_actions` call in `gui/main_window.py`. A spin box on the Sessions tab
(`gui/panels/sessions_panel.py`'s `match_tolerance_spin`) lets a human tune it per project; changing
it updates `project.action_match_tolerance_px` directly (`_on_match_tolerance_changed`). No
per-region override exists (a single project-wide value only) -- left as a further refinement if one
project's HUD ever needs different tolerances in different areas of the screen.

**G9. Pattern-matching is O(gestures × actions).** *(status: open, no action needed yet)*
Fine at today's scale (a HUD-driven game's action library — tens, not thousands). Worth remembering
if this pipeline is later run over large recorded corpora for behavior-cloning-style dataset
generation rather than one-off IDE sessions, per the stated eventual Gym/Game-Run consumers of this
library. Revisit only if a real project's session/action counts make this measurably slow.

**G11. A classified session/Game Run needs to be shareable across devices with a different
resolution and/or a different frame/game rate.** *(status: Fixed)* The user's own use case: record
and classify a playthrough on one device, then share the resulting Actions/HUD Regions/Game Run
with other people playing the *same game* on their *own*, likely different, devices. Two
independent axes of "different device," requiring two different solutions since only one of them
is actually measurable at runtime:

- **Screen resolution — solved automatically, no manual factor needed.** Every stored `(x, y)` was
  already in the project's own reference resolution (`Project.reference_width/height`), but
  `LiveConnection.send_primitive` previously required that value to *already* equal whatever
  device it was connected to -- `agent_client.touch_message`'s own docstring is explicit that
  `irobot_server`'s `PositionMapper.map()` requires an exact `Size.equals()` match on `screen_size`
  or it silently drops the event, so opening a shared project against a different-resolution
  device meant either every touch landing in the wrong place or being dropped outright, and the
  existing "Apply Detected Resolution" button only ever rewrote the *label*, not the coordinates
  (its own log line said so: "existing event coordinates stay numerically the same"). Fixed:
  `send_primitive` now compares the authored reference resolution it's given against this
  connection's own `latest_resolution()` (already-existing live detection, `BLOB_MSG_TYPE_RESOLUTION`)
  and, when they differ, rescales `(x, y)` into the device's real resolution via the new
  `model.scale_point` (extracted from `_scale_rect`'s existing per-axis linear scaling) before
  sending, using the *device's* real size as `screen_size` rather than the project's own --
  satisfying `PositionMapper`'s exact-match requirement while still landing at the proportionally
  correct spot. This needs no user action at all: connect to a different device and positions
  just work. Tests: `ResolutionRescaleTest` in the new `test_connection.py`.
- **Frame/game rate — cannot be auto-detected, so it's a manual per-recipient factor.** Unlike
  resolution, there's no wire message reporting "how fast this device's game logic actually runs,"
  so this can't be solved the same way. Fixed: `Project.time_scale` (default `1.0`, persisted like
  `action_match_tolerance_px`) multiplies every `WAIT`/`DELAY` frame's real-ms duration
  (`connection.FRAME_MS`) at the one place all of them ultimately sleep --
  `LiveConnection.send_primitive`'s WAIT handling, and `run_engine.GameRunExecutor`/
  `session_replay.SessionPlayer`'s own `_sleep_frames`, both of which already hold a
  `self.connection` to read it from. A spin box next to Reference width/height in the main project
  form lets a recipient tune it for their own device without touching a single recorded `frames`
  value; `1.0` reproduces the original author's pacing exactly, since each recipient's own copy of
  `project.yaml` is independently editable (sharing here just means copying the project directory
  -- no separate "local override" layer needed). Tests: `TimeScaleTest` in `test_connection.py`.

**The combined result**: "the original is the base," per the user's own framing -- a shared
project's Actions/HUD Regions/Sessions/Game Runs are untouched, portable data; a recipient opens
them, connects to their own device (resolution handled automatically), and dials in one `time_scale`
number until pacing feels right, without editing any recorded coordinate or frame count by hand.

## 4. Build order followed

All of G1–G6 and G8 landed together in one pass rather than the incremental order originally
sketched below, since the underlying model changes (particularly G1's rename cascade and G3's
distance-ranked matching) turned out to share enough surface area with G2/G4/G5/G6/G8 that
implementing them separately would have meant repeatedly re-touching the same functions. The
original reasoning for relative priority still holds and is preserved here for context:

1. **G1** (rename cascade) — first, since it's the one gap that could actively corrupt the iterate
   loop the rest of this doc's process depends on.
2. **G3** (nearest-match, not first-match) — directly improves match quality as the library grows,
   the process's core selling point.
3. **G2** (surface pattern-matched segments distinctly) — small logging/labeling change, big trust
   improvement for the "verify" half of the loop.
4. **G6** (coordinates in unknown proposals) — cheap, no dependencies.
5. **G4** (diff view on reclassify) — biggest ergonomics win for repeated iteration.
6. **G5** (`propose_combos`) — closes the combo-side asymmetry once the single-region path is solid.
7. **G8** — a config surface, once the tolerance value it exposes was actually being used consistently
   everywhere (G1–G5 all touch call sites that needed the same threading).
8. **G7** — a decision to record, not a code change; recorded above.
9. **G9** — deliberately left open; revisit only at real scale.

Every function above is covered by the existing pure-Python suite
(`irobot_gym_ide/tests/test_model.py`, `test_hud_classifier.py`) — no device required. Full suite:
160 tests passing as of this update.
