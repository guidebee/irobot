"""Classifies a GameplaySession's raw gesture stream against a project's
HudRegions -- no clustering, no ML: a gesture's classification is just "which
HudRegion, if any, contains the point where it started" (see model.py's
HudRegion docstring for why no frame-size scaling is needed here, unlike
ImageTemplate). Produces SessionSegments a caller assigns to
GameplaySession.segments (or merges with existing ones) -- this module never
mutates the session itself, same "propose, don't apply" spirit as every other
suggestion-producing piece in this codebase (see GAME_RUN_AI_ASSIST_DESIGN.md
§3's human-review precedent).

Two (or more) regions touched at overlapping times are folded into a single
combo segment -- see model.py's HudRegionCombo -- only when their exact set
of region names matches a combo an author explicitly defined; unmatched
concurrent touches fall back to a separate segment per region, same as if no
combo existed. Overlap here uses the same definition GameplaySession.validate
already uses (a running max of end_index), so a cluster this module folds
into one combo is exactly the span validate() would otherwise flag as
"overlaps the previous segment".

See propose_actions(), below, for the companion step that turns an already-classified
session's segments (plus any gesture no HudRegion covered at all) into real proposed
Actions -- same propose-don't-apply spirit, just one step further down the pipeline.
propose_combos() is that same bootstrap for the *combo* side (a recurring concurrent-region
cluster with no matching HudRegionCombo yet), and diff_classifications() lets a caller show
what a fresh classification would actually change before overwriting a session's existing
segments. build_game_run() turns an already-classified session into a real, editable
GameRun graph -- the durable counterpart to session_replay.py's one-shot "Replay Classified"
loop. compare_replay_durations() checks classification against a very different kind of
mistake than a wrong label: a segment whose action's own scripted timing is nowhere near how
long that gesture actually took to record, which silently makes "Replay Classified" run much
faster (or slower) than "Replay Raw" even though every segment is correctly *named*. See
ACTION_CLASSIFICATION_DESIGN.md for the full design and the gaps (G1-G10) these functions
close.
"""
from __future__ import annotations

import copy

from .model import (
    Action, EventKind, GameplaySession, GameRun, HudRegion, HudRegionCombo, RunEdge, RunNode, RunNodeKind,
    SessionSegment, find_matching_action, frames_between,
)


def _best_region(regions: list, x, y) -> HudRegion | None:
    """The smallest-area HudRegion containing (x, y), ties broken by name for
    determinism -- see HudRegion's docstring: an author deliberately
    overlapping two regions (e.g. a broad "attack area" behind a small
    "special move" hotspot) means the more specific (smaller) one should
    win."""
    candidates = [r for r in regions if r.contains(x, y)]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (r.area, r.name))


def _gesture_hits(session: GameplaySession, region_list: list, project_actions: dict,
                   position_tolerance_px: int, on_log) -> tuple:
    """First pass: finds every gesture's (start_index, end_index, HudRegion) hit, in
    start_index order, without yet deciding segments vs. combos. A gesture that lands
    outside every HudRegion gets one more chance before being left a genuine miss: if its
    own raw events "look alike" (model.events_look_alike) some action already in
    `project_actions`, it's classified directly against that action's name -- this is what
    lets classification quality compound over time (see propose_actions' own docstring for
    the full loop): once a human names and keeps a proposed action, later recordings of
    that same physical gesture are recognized even where no HudRegion happens to cover it.
    HudRegions still take priority when both would apply -- they're an explicit, authored
    spatial mapping, a stronger signal than "this looks like it" pattern matching. When more
    than one existing action is within tolerance of a gesture, `model.find_matching_action`
    picks the nearest one but this still logs the ambiguity (every candidate name, nearest
    first) so a human notices the library has gotten crowded in that spot (see
    ACTION_CLASSIFICATION_DESIGN.md G3).

    Returns (hits, pattern_segments, pattern_matched_count, total_gesture_count) --
    total_gesture_count includes gestures that matched neither a region nor an existing
    action's pattern, for the summary log line."""
    hits = []
    pattern_segments = []
    pattern_matched = 0
    total_gestures = 0
    open_start: dict = {}   # pointer_id -> index of its open PRESS

    def _on_ambiguous(candidates: list) -> None:
        on_log(f"Note: gesture matched {len(candidates)} existing actions within tolerance "
               f"({', '.join(candidates)}) -- picked the nearest, {candidates[0]!r}.")

    def _match(events: list) -> str | None:
        return find_matching_action(events, project_actions, position_tolerance_px, on_ambiguous=_on_ambiguous)

    def _try_pattern_match(start: int, end: int) -> bool:
        nonlocal pattern_matched
        if not project_actions:
            return False
        name = _match(session.events[start:end])
        if name:
            pattern_segments.append(SessionSegment(start_index=start, end_index=end, action_name=name,
                                                     label=f"pattern:{name}"))
            pattern_matched += 1
            return True
        if end - start > 1:
            # whole-gesture match failed -- try it as a hold's press/release bookend pair,
            # same split model.HudRegion.is_hold regions use (see _region_segments).
            press_name = _match(session.events[start:start + 1])
            release_name = _match(session.events[end - 1:end])
            if press_name and release_name:
                pattern_segments.append(SessionSegment(start_index=start, end_index=start + 1,
                                                         action_name=press_name, label=f"pattern:{press_name}"))
                pattern_segments.append(SessionSegment(start_index=end - 1, end_index=end,
                                                         action_name=release_name, label=f"pattern:{release_name}"))
                pattern_matched += 1
                return True
        return False

    for i, event in enumerate(session.events):
        if event.kind == EventKind.TAP:
            total_gestures += 1
            if event.x is None or event.y is None:
                continue
            region = _best_region(region_list, event.x, event.y)
            if region is not None:
                hits.append((i, i + 1, region))
            else:
                _try_pattern_match(i, i + 1)
        elif event.kind == EventKind.PRESS:
            if event.pointer_id in open_start:
                on_log(f"event {i}: PRESS on pointer {event.pointer_id} which is already held, "
                       f"treating as a new gesture start")
            open_start[event.pointer_id] = i
        elif event.kind == EventKind.RELEASE:
            start = open_start.pop(event.pointer_id, None)
            if start is None:
                on_log(f"event {i}: RELEASE on pointer {event.pointer_id} with no open PRESS, skipped")
                continue
            total_gestures += 1
            press_event = session.events[start]
            if press_event.x is None or press_event.y is None:
                continue
            region = _best_region(region_list, press_event.x, press_event.y)
            if region is not None:
                hits.append((start, i + 1, region))
            else:
                _try_pattern_match(start, i + 1)

    hits.sort(key=lambda h: h[0])
    return hits, pattern_segments, pattern_matched, total_gestures


def _cluster_overlapping(hits: list) -> list:
    """Groups `hits` (sorted by start_index) into clusters of mutually
    time-overlapping gestures, using the same running-max-of-end_index
    definition of "overlaps" GameplaySession.validate() uses -- a cluster of
    one is just a normal, non-overlapping gesture. Returns a list of
    clusters, each a list of (start_index, end_index, HudRegion)."""
    clusters = []
    current: list = []
    current_end = None
    for hit in hits:
        start, end, _region = hit
        if current and start < current_end:
            current.append(hit)
            current_end = max(current_end, end)
        else:
            if current:
                clusters.append(current)
            current = [hit]
            current_end = end
    if current:
        clusters.append(current)
    return clusters


def _region_segments(start: int, end: int, region: HudRegion) -> list:
    """Segment(s) for one classified (start, end) hit against `region`. A
    plain region produces the one span segment classify_session always
    produced. A hold region (region.is_hold, see model.HudRegion) instead
    produces two bookend segments -- one at the gesture's press index naming
    `region.action_name` (the "start" action), one at its release index
    naming `region.release_action_name` (the "stop" action) -- so replay
    fires the real start/stop actions at the real recorded times instead of
    running one fixed-length action for the whole held span. A TAP-derived
    hit (end == start + 1) still gets both bookends at that same single
    index -- a quick tap on a hold region is a genuine down-then-up, just
    too fast to have produced a separate PRESS/RELEASE pair."""
    if not region.is_hold:
        return [SessionSegment(start_index=start, end_index=end, action_name=region.action_name, label=region.name)]
    return [
        SessionSegment(start_index=start, end_index=start + 1, action_name=region.action_name, label=region.name),
        SessionSegment(start_index=end - 1, end_index=end, action_name=region.release_action_name, label=region.name),
    ]


def classify_session(session: GameplaySession, regions: dict, combos: dict = None,
                      project_actions: dict = None, position_tolerance_px: int = 30, on_log=None) -> list:
    """Returns SessionSegments for every gesture in `session.events` whose
    starting point (a TAP's own point, or a PRESS/RELEASE pair's PRESS point)
    falls inside some HudRegion in `regions` (dict[str, HudRegion], i.e.
    project.hud_regions), OR -- for a gesture outside every region -- whose
    own raw events match an existing action in `project_actions`
    (dict[str, Action], i.e. project.actions; optional, defaults to none) per
    model.find_matching_action (within `position_tolerance_px`, i.e.
    project.action_match_tolerance_px); see _gesture_hits for why HudRegions
    still take priority when both would apply. A gesture matching neither --
    or a KEY event, which has no (x, y) at all -- produces no segment: left
    unclassified for raw replay or a human/future step to handle, never
    guessed at.

    `combos` (dict[str, HudRegionCombo], i.e. project.hud_region_combos)
    lets two or more regions touched at overlapping times collapse into one
    segment naming the combo's own action instead of one segment per region
    -- see model.py's HudRegionCombo and this module's docstring for exactly
    when that applies (action-pattern matches never participate in combos --
    each already names one complete, specific action on its own). Pure
    function: does not mutate `session`.

    The summary log line breaks matched gestures down by *how* each one
    matched (HUD region / HUD combo / existing-action pattern) -- see
    ACTION_CLASSIFICATION_DESIGN.md G2: a pattern match is a fuzzier,
    tolerance-based signal than a HUD region's crisp point-in-rect test, so a
    human reviewing the log has a cheap way to tell which segments are worth
    a second glance rather than only ever seeing the outright-unknown count."""
    on_log = on_log or (lambda msg: None)
    combos = combos or {}
    project_actions = project_actions or {}
    combo_by_region_set = {frozenset(c.region_names): c for c in combos.values()}
    region_list = list(regions.values())

    hits, pattern_segments, pattern_matched, total_gestures = _gesture_hits(
        session, region_list, project_actions, position_tolerance_px, on_log)
    segments = list(pattern_segments)
    region_matched = 0
    combo_matched = 0

    for cluster in _cluster_overlapping(hits):
        if len(cluster) == 1:
            start, end, region = cluster[0]
            segments.extend(_region_segments(start, end, region))
            region_matched += 1
            continue

        region_names = frozenset(region.name for _s, _e, region in cluster)
        combo = combo_by_region_set.get(region_names)
        if combo is not None:
            start = min(s for s, _e, _r in cluster)
            end = max(e for _s, e, _r in cluster)
            segments.append(SessionSegment(
                start_index=start, end_index=end, action_name=combo.action_name, label=combo.name))
            combo_matched += len(cluster)
        else:
            on_log(f"{len(cluster)} concurrent gesture(s) across regions {sorted(region_names)} have no "
                   f"matching HudRegionCombo -- classified separately (see HUD Combos).")
            for start, end, region in cluster:
                segments.extend(_region_segments(start, end, region))
            region_matched += len(cluster)

    segments.sort(key=lambda s: s.start_index)
    matched_gestures = pattern_matched + region_matched + combo_matched
    on_log(f"Classified {matched_gestures} of {total_gestures} gesture(s) against {len(region_list)} HUD "
           f"region(s) and {len(project_actions)} existing action(s): {region_matched} via HUD region, "
           f"{combo_matched} via HUD combo, {pattern_matched} via existing-action pattern "
           f"({total_gestures - matched_gestures} unmatched).")
    return segments


def diff_classifications(old_segments: list, new_segments: list) -> dict:
    """Compares a session's previous `segments` against a freshly computed classification,
    keyed by (start_index, end_index) span, for a caller to show *what would change* before
    committing to an overwrite (see ACTION_CLASSIFICATION_DESIGN.md G4 -- the iterate step
    §1.5 describes is only legible if a human can see whether reclassifying actually helped).
    Returns counts: 'unchanged' (same span, same action_name), 'changed' (same span, a
    different action_name than before), 'added' (a span with no old segment at all --
    typically a gesture that was previously unclassified/unknown and now resolves), 'removed'
    (an old span the new classification no longer produces at all). Pure function."""
    old_by_span = {(s.start_index, s.end_index): s.action_name for s in old_segments}
    new_by_span = {(s.start_index, s.end_index): s.action_name for s in new_segments}
    unchanged = sum(1 for span, name in new_by_span.items() if old_by_span.get(span) == name)
    changed = sum(1 for span, name in new_by_span.items() if span in old_by_span and old_by_span[span] != name)
    added = sum(1 for span in new_by_span if span not in old_by_span)
    removed = sum(1 for span in old_by_span if span not in new_by_span)
    return {"unchanged": unchanged, "changed": changed, "added": added, "removed": removed}


def propose_combos(session: GameplaySession, regions: dict, combos: dict = None, on_log=None) -> dict:
    """Finds every concurrent-region cluster in `session.events` whose exact region-name set
    doesn't match any HudRegionCombo already in `combos`, and proposes one new combo per
    distinct region-name set encountered -- named by joining the involved region names (e.g.
    "jump_button+right_button"), with `action_name` set to that same generated name. This is
    the combo-side sibling of propose_actions' `unknown_N` bootstrap (see
    ACTION_CLASSIFICATION_DESIGN.md G5): classify_session today only logs a warning for an
    unmatched concurrent cluster (see its "...have no matching HudRegionCombo" line), leaving
    a human to notice it in the log and hand-author the combo. Accepting a proposal here
    doesn't by itself create the backing Action -- the *next* classify_session run folds the
    cluster into one segment naming the combo's action_name, and propose_actions then
    proposes that action from the cluster's own raw events, exactly like any other
    not-yet-real action name. Pure function: returns dict[name, HudRegionCombo], never
    mutates `session`/`regions`/`combos`."""
    on_log = on_log or (lambda msg: None)
    combos = combos or {}
    known_sets = {frozenset(c.region_names) for c in combos.values()}
    region_list = list(regions.values())

    hits, _pattern_segments, _pattern_matched, _total = _gesture_hits(session, region_list, {}, 30, on_log)
    proposals: dict = {}
    for cluster in _cluster_overlapping(hits):
        if len(cluster) < 2:
            continue
        region_names = frozenset(region.name for _s, _e, region in cluster)
        proposed_sets = {frozenset(c.region_names) for c in proposals.values()}
        if region_names in known_sets or region_names in proposed_sets:
            continue
        name = "+".join(sorted(region_names))
        proposals[name] = HudRegionCombo(name=name, region_names=sorted(region_names), action_name=name)
        on_log(f"Proposed HUD combo {name!r} for regions {sorted(region_names)} touched concurrently "
               f"with no matching combo defined.")
    return proposals


def _next_unknown_name(prefix: str, taken: set) -> str:
    n = 1
    while f"{prefix}_{n}" in taken:
        n += 1
    return f"{prefix}_{n}"


def propose_actions(session: GameplaySession, project_actions: dict, unknown_prefix: str = "unknown",
                     position_tolerance_px: int = 30, on_log=None) -> dict:
    """Builds one proposed Action per name `session.segments` refers to that isn't already a
    real project action, plus a placeholder Action (named `unknown_1`, `unknown_2`, ... --
    never colliding with an existing action name or an earlier placeholder from this same
    call) for every raw gesture in `session.events` that no segment covers at all. Each
    proposed Action's events are a deep copy of the exact recorded slice they came from, so a
    human reviewing/renaming/re-editing them in the Inspector is editing what was actually
    recorded, same spirit as device_recorder.py's own recorded-gesture-to-Action path.

    Never overwrites an existing action: a proposal whose NAME collides with one in
    `project_actions` (dict[str, Action], i.e. project.actions) is skipped outright. A
    proposal whose name is new but whose EVENTS look like an existing action's (per
    model.find_matching_action -- the same physical gesture already captured under a
    different name) is still proposed, but flagged: its description gets a "possible
    duplicate of ..." hint so a human can tell at a glance and delete the redundant one
    later, rather than silently dropping something that might in fact be a genuinely
    different action that just happens to look similar. This is the other half of the
    "gradually improve the action library" loop classify_session's own pattern-matching
    fallback starts: propose it named and flagged here, human accepts/renames/deletes it,
    and the next classify_session run recognizes that same gesture directly.

    Requires `session.segments` to already be populated (i.e. classify_session has already run
    against it) -- this function does not classify anything itself, it only fills the two gaps
    classification alone leaves: a HudRegion/HudRegionCombo whose action_name was authored but
    never turned into a real Action yet, and gestures that landed outside every HudRegion (and
    didn't pattern-match an existing action either).

    Pure function, same "propose, don't apply" convention as classify_session itself: returns
    dict[name, Action] and never mutates `session` or `project_actions` -- it is the caller's
    job to decide which (if any) proposals to add via Project.add_action."""
    on_log = on_log or (lambda msg: None)
    existing_action_names = set(project_actions)
    proposals: dict = {}

    def _flag_if_duplicate(action: Action) -> None:
        def _on_ambiguous(candidates: list) -> None:
            on_log(f"Note: proposed action {action.name!r} looks like {len(candidates)} existing actions "
                   f"({', '.join(candidates)}) -- flagged against the nearest, {candidates[0]!r}.")
        dup_name = find_matching_action(action.events, project_actions, position_tolerance_px,
                                         on_ambiguous=_on_ambiguous)
        if dup_name:
            action.description += f" -- possible duplicate of {dup_name!r}; review and delete one if redundant."
            on_log(f"Note: proposed action {action.name!r} looks like existing action {dup_name!r}.")

    def _location(events: list) -> str:
        for e in events:
            if e.x is not None and e.y is not None:
                return f" at ({e.x}, {e.y})"
        return ""

    covered = [False] * len(session.events)
    for seg in session.segments:
        for i in range(seg.start_index, seg.end_index):
            covered[i] = True
        if seg.action_name and seg.action_name not in existing_action_names and seg.action_name not in proposals:
            events = copy.deepcopy(session.events[seg.start_index:seg.end_index])
            action = Action(
                name=seg.action_name,
                description=f"proposed from session {session.name!r}{_location(events)} "
                            f"(classified as {seg.label or seg.action_name!r})",
                events=events,
            )
            _flag_if_duplicate(action)
            proposals[seg.action_name] = action
            on_log(f"Proposed action {seg.action_name!r} from session {session.name!r}.")

    def _propose_unknown(start: int, end: int) -> None:
        name = _next_unknown_name(unknown_prefix, existing_action_names | proposals.keys())
        events = copy.deepcopy(session.events[start:end])
        action = Action(
            name=name,
            description=f"unclassified gesture from session {session.name!r}{_location(events)} -- "
                        f"rename and edit as needed",
            events=events,
        )
        _flag_if_duplicate(action)
        proposals[name] = action
        on_log(f"Proposed placeholder action {name!r}{_location(events)} for an unclassified gesture "
               f"in session {session.name!r}.")

    open_start: dict = {}
    for i, event in enumerate(session.events):
        if event.kind == EventKind.TAP:
            if not covered[i]:
                _propose_unknown(i, i + 1)
        elif event.kind == EventKind.PRESS:
            open_start[event.pointer_id] = i
        elif event.kind == EventKind.RELEASE:
            start = open_start.pop(event.pointer_id, None)
            if start is None:
                continue
            end = i + 1
            if not any(covered[start:end]):
                _propose_unknown(start, end)

    return proposals


def build_game_run(session: GameplaySession, name: str, project_actions: dict = None) -> GameRun:
    """Turns an already-classified session into a GameRun graph: one ACTION node per segment
    in `session.segments` (in start_index order), each preceded by a DELAY node reproducing
    the real recorded gap (in frames, via model.frames_between) before it fires -- omitted
    when that gap is zero, so two back-to-back segments chain directly. All nodes are chained
    sequentially by edges into one straight-line run, laid out left-to-right for the canvas.

    This is the durable, GUI-editable counterpart to session_replay.py's "Replay Classified"
    (which is the IDE's own ad hoc "run it once and watch the log" loop, per that module's
    docstring, and reproduces this exact same node-by-node/gap-by-gap sequence at replay
    time rather than saving it anywhere) -- accepting the result here turns one recorded
    playthrough into a reusable macro alongside any hand-authored Run, addressable from
    Call-Run or the Game Run tab like any other, editable (insert a Repeat, a Compare, split
    it up) instead of being replayed from the Sessions tab every time. Same self-correction
    too: when `project_actions` (dict[str, Action], i.e. project.actions) is given, a segment
    whose own recorded span took longer than its action's own WAIT total gets an extra
    "catch-up" DELAY node appended right after its ACTION node, so running this graph via
    run_engine.py paces at roughly the real recorded duration instead of silently running
    however long the action's own script happens to take (see
    session_replay.replay_classified's matching catch-up sleep and
    ACTION_CLASSIFICATION_DESIGN.md G10). Omitted when `project_actions` isn't given, or for
    a segment whose action already takes at least as long as it really did.

    Requires `session.segments` to already be populated (classify_session has already run).
    A segment naming an action absent from the project is still included as-is -- this
    function has no project actions dict to check against, and GameRun.validate() already
    flags an unknown action_name the same way it would for a hand-authored graph, so nothing
    is silently dropped. Pure function: returns a new GameRun, never mutates `session`."""
    project_actions = project_actions or {}
    segments = sorted(session.segments, key=lambda s: s.start_index)
    run = GameRun(name=name)
    if not segments:
        return run

    x = 40.0
    prev_id = None
    prev_end = 0
    for i, seg in enumerate(segments):
        gap_frames = frames_between(session.events, prev_end, seg.start_index)
        if gap_frames > 0:
            delay_id = f"delay{i}"
            run.add_node(RunNode(id=delay_id, kind=RunNodeKind.DELAY, x=x, y=40.0, frames=gap_frames))
            if prev_id is not None:
                run.add_edge(RunEdge(id=f"e{len(run.edges)}", source=prev_id, target=delay_id))
            prev_id = delay_id
            x += 200.0

        action_id = f"action{i}"
        run.add_node(RunNode(id=action_id, kind=RunNodeKind.ACTION, x=x, y=40.0, action_name=seg.action_name))
        if prev_id is not None:
            run.add_edge(RunEdge(id=f"e{len(run.edges)}", source=prev_id, target=action_id))
        prev_id = action_id
        x += 200.0
        prev_end = seg.end_index

        action = project_actions.get(seg.action_name)
        if action is not None:
            recorded_frames = frames_between(session.events, seg.start_index, seg.end_index)
            action_frames = sum(e.frames for e in action.events if e.kind == EventKind.WAIT)
            catchup = recorded_frames - action_frames
            if catchup > 0:
                catchup_id = f"catchup{i}"
                run.add_node(RunNode(id=catchup_id, kind=RunNodeKind.DELAY, x=x, y=40.0, frames=catchup))
                run.add_edge(RunEdge(id=f"e{len(run.edges)}", source=prev_id, target=catchup_id))
                prev_id = catchup_id
                x += 200.0

    return run


def compare_replay_durations(session: GameplaySession, project_actions: dict, mismatch_threshold_frames: int = 3) -> dict:
    """Checks classification against a very different kind of mistake than a wrong label: a
    segment whose real recorded span took far longer (or shorter) to actually happen than its
    named action's own scripted WAIT total -- which silently makes "Replay Classified" run
    much faster or slower overall than "Replay Raw", even though every segment is classified
    under the exactly-correct name (see ACTION_CLASSIFICATION_DESIGN.md G10 -- discovered when
    a HudRegionCombo folded a long "hold right while mashing jump" span into the combo
    action's own few-frame canned macro: fine as a *label*, very wrong as a *replay*).

    Returns {"raw_frames", "classified_frames", "mismatches"}:
      raw_frames        -- total WAIT frames in session.events, i.e. what "Replay Raw" takes.
      classified_frames -- total frames "Replay Classified" would actually take: the sum,
                            over `session.segments` in order, of the real gap before each one
                            (model.frames_between) plus that segment's own action's own
                            internal WAIT total (0 if the action is missing/unresolvable --
                            session.validate() already flags that separately).
      mismatches        -- list of (label, action_name, recorded_frames, action_frames) for
                            every segment whose own recorded span duration
                            (model.frames_between over just that segment's [start, end))
                            differs from its action's own WAIT total by more than
                            `mismatch_threshold_frames` -- the concrete, per-segment
                            breakdown of *why* the two totals diverge, not just that they do.
    Pure function; does not replay anything or mutate `session`."""
    raw_frames = sum(e.frames for e in session.events if e.kind == EventKind.WAIT)
    segments = sorted(session.segments, key=lambda s: s.start_index)
    classified_frames = 0
    mismatches = []
    prev_end = 0
    for seg in segments:
        classified_frames += frames_between(session.events, prev_end, seg.start_index)
        recorded_frames = frames_between(session.events, seg.start_index, seg.end_index)
        action = project_actions.get(seg.action_name)
        action_frames = sum(e.frames for e in action.events if e.kind == EventKind.WAIT) if action else 0
        classified_frames += action_frames
        if abs(recorded_frames - action_frames) > mismatch_threshold_frames:
            mismatches.append((seg.label or seg.action_name, seg.action_name, recorded_frames, action_frames))
        prev_end = seg.end_index
    return {"raw_frames": raw_frames, "classified_frames": classified_frames, "mismatches": mismatches}

    return proposals
