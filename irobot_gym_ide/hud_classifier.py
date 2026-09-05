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
"""
from __future__ import annotations

import copy

from .model import Action, EventKind, GameplaySession, HudRegion, SessionSegment, find_matching_action


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


def _gesture_hits(session: GameplaySession, region_list: list, project_actions: dict, on_log) -> tuple:
    """First pass: finds every gesture's (start_index, end_index, HudRegion) hit, in
    start_index order, without yet deciding segments vs. combos. A gesture that lands
    outside every HudRegion gets one more chance before being left a genuine miss: if its
    own raw events "look alike" (model.events_look_alike) some action already in
    `project_actions`, it's classified directly against that action's name -- this is what
    lets classification quality compound over time (see propose_actions' own docstring for
    the full loop): once a human names and keeps a proposed action, later recordings of
    that same physical gesture are recognized even where no HudRegion happens to cover it.
    HudRegions still take priority when both would apply -- they're an explicit, authored
    spatial mapping, a stronger signal than "this looks like it" pattern matching.

    Returns (hits, pattern_segments, pattern_matched_count, total_gesture_count) --
    total_gesture_count includes gestures that matched neither a region nor an existing
    action's pattern, for the summary log line."""
    hits = []
    pattern_segments = []
    pattern_matched = 0
    total_gestures = 0
    open_start: dict = {}   # pointer_id -> index of its open PRESS

    def _try_pattern_match(start: int, end: int) -> bool:
        nonlocal pattern_matched
        if not project_actions:
            return False
        name = find_matching_action(session.events[start:end], project_actions)
        if name:
            pattern_segments.append(SessionSegment(start_index=start, end_index=end, action_name=name,
                                                     label=f"pattern:{name}"))
            pattern_matched += 1
            return True
        if end - start > 1:
            # whole-gesture match failed -- try it as a hold's press/release bookend pair,
            # same split model.HudRegion.is_hold regions use (see _region_segments).
            press_name = find_matching_action(session.events[start:start + 1], project_actions)
            release_name = find_matching_action(session.events[end - 1:end], project_actions)
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
                      project_actions: dict = None, on_log=None) -> list:
    """Returns SessionSegments for every gesture in `session.events` whose
    starting point (a TAP's own point, or a PRESS/RELEASE pair's PRESS point)
    falls inside some HudRegion in `regions` (dict[str, HudRegion], i.e.
    project.hud_regions), OR -- for a gesture outside every region -- whose
    own raw events match an existing action in `project_actions`
    (dict[str, Action], i.e. project.actions; optional, defaults to none) per
    model.find_matching_action; see _gesture_hits for why HudRegions still
    take priority when both would apply. A gesture matching neither -- or a
    KEY event, which has no (x, y) at all -- produces no segment: left
    unclassified for raw replay or a human/future step to handle, never
    guessed at.

    `combos` (dict[str, HudRegionCombo], i.e. project.hud_region_combos)
    lets two or more regions touched at overlapping times collapse into one
    segment naming the combo's own action instead of one segment per region
    -- see model.py's HudRegionCombo and this module's docstring for exactly
    when that applies (action-pattern matches never participate in combos --
    each already names one complete, specific action on its own). Pure
    function: does not mutate `session`."""
    on_log = on_log or (lambda msg: None)
    combos = combos or {}
    project_actions = project_actions or {}
    combo_by_region_set = {frozenset(c.region_names): c for c in combos.values()}
    region_list = list(regions.values())

    hits, pattern_segments, matched_gestures, total_gestures = _gesture_hits(
        session, region_list, project_actions, on_log)
    segments = list(pattern_segments)

    for cluster in _cluster_overlapping(hits):
        if len(cluster) == 1:
            start, end, region = cluster[0]
            segments.extend(_region_segments(start, end, region))
            matched_gestures += 1
            continue

        region_names = frozenset(region.name for _s, _e, region in cluster)
        combo = combo_by_region_set.get(region_names)
        if combo is not None:
            start = min(s for s, _e, _r in cluster)
            end = max(e for _s, e, _r in cluster)
            segments.append(SessionSegment(
                start_index=start, end_index=end, action_name=combo.action_name, label=combo.name))
            matched_gestures += len(cluster)
        else:
            on_log(f"{len(cluster)} concurrent gesture(s) across regions {sorted(region_names)} have no "
                   f"matching HudRegionCombo -- classified separately (see HUD Combos).")
            for start, end, region in cluster:
                segments.extend(_region_segments(start, end, region))
            matched_gestures += len(cluster)

    segments.sort(key=lambda s: s.start_index)
    on_log(f"Classified {matched_gestures} of {total_gestures} gesture(s) against {len(region_list)} HUD "
           f"region(s) and {len(project_actions)} existing action(s) ({total_gestures - matched_gestures} "
           f"unmatched).")
    return segments


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
        dup_name = find_matching_action(action.events, project_actions, position_tolerance_px)
        if dup_name:
            action.description += f" -- possible duplicate of {dup_name!r}; review and delete one if redundant."
            on_log(f"Note: proposed action {action.name!r} looks like existing action {dup_name!r}.")

    covered = [False] * len(session.events)
    for seg in session.segments:
        for i in range(seg.start_index, seg.end_index):
            covered[i] = True
        if seg.action_name and seg.action_name not in existing_action_names and seg.action_name not in proposals:
            action = Action(
                name=seg.action_name,
                description=f"proposed from session {session.name!r} (classified as {seg.label or seg.action_name!r})",
                events=copy.deepcopy(session.events[seg.start_index:seg.end_index]),
            )
            _flag_if_duplicate(action)
            proposals[seg.action_name] = action
            on_log(f"Proposed action {seg.action_name!r} from session {session.name!r}.")

    def _propose_unknown(start: int, end: int) -> None:
        name = _next_unknown_name(unknown_prefix, existing_action_names | proposals.keys())
        action = Action(
            name=name,
            description=f"unclassified gesture from session {session.name!r} -- rename and edit as needed",
            events=copy.deepcopy(session.events[start:end]),
        )
        _flag_if_duplicate(action)
        proposals[name] = action
        on_log(f"Proposed placeholder action {name!r} for an unclassified gesture in session {session.name!r}.")

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
