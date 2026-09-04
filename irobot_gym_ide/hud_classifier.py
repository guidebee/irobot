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
"""
from __future__ import annotations

from .model import EventKind, GameplaySession, HudRegion, SessionSegment


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


def _gesture_hits(session: GameplaySession, region_list: list, on_log) -> tuple:
    """First pass: finds every gesture's (start_index, end_index, HudRegion)
    hit, in start_index order, without yet deciding segments vs. combos.
    Returns (hits, total_gesture_count) -- total_gesture_count includes
    gestures that matched no region at all, for the summary log line."""
    hits = []
    total_gestures = 0
    open_start: dict = {}   # pointer_id -> index of its open PRESS

    for i, event in enumerate(session.events):
        if event.kind == EventKind.TAP:
            total_gestures += 1
            if event.x is None or event.y is None:
                continue
            region = _best_region(region_list, event.x, event.y)
            if region is not None:
                hits.append((i, i + 1, region))
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

    hits.sort(key=lambda h: h[0])
    return hits, total_gestures


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


def classify_session(session: GameplaySession, regions: dict, combos: dict = None, on_log=None) -> list:
    """Returns SessionSegments for every gesture in `session.events` whose
    starting point (a TAP's own point, or a PRESS/RELEASE pair's PRESS point)
    falls inside some HudRegion in `regions` (dict[str, HudRegion], i.e.
    project.hud_regions). A gesture landing outside every region -- or a KEY
    event, which has no (x, y) at all -- produces no segment: left
    unclassified for raw replay or a human/future step to handle, never
    guessed at.

    `combos` (dict[str, HudRegionCombo], i.e. project.hud_region_combos)
    lets two or more regions touched at overlapping times collapse into one
    segment naming the combo's own action instead of one segment per region
    -- see model.py's HudRegionCombo and this module's docstring for exactly
    when that applies. Pure function: does not mutate `session`."""
    on_log = on_log or (lambda msg: None)
    combos = combos or {}
    combo_by_region_set = {frozenset(c.region_names): c for c in combos.values()}
    region_list = list(regions.values())

    hits, total_gestures = _gesture_hits(session, region_list, on_log)
    matched_gestures = 0
    segments = []

    for cluster in _cluster_overlapping(hits):
        if len(cluster) == 1:
            start, end, region = cluster[0]
            segments.append(SessionSegment(
                start_index=start, end_index=end, action_name=region.action_name, label=region.name))
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
                segments.append(SessionSegment(
                    start_index=start, end_index=end, action_name=region.action_name, label=region.name))
            matched_gestures += len(cluster)

    segments.sort(key=lambda s: s.start_index)
    on_log(f"Classified {matched_gestures} of {total_gestures} gesture(s) against {len(region_list)} HUD "
           f"region(s) ({total_gestures - matched_gestures} unmatched).")
    return segments
