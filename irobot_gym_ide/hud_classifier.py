"""Classifies a GameplaySession's raw gesture stream against a project's
HudRegions -- no clustering, no ML: a gesture's classification is just "which
HudRegion, if any, contains the point where it started" (see model.py's
HudRegion docstring for why no frame-size scaling is needed here, unlike
ImageTemplate). Produces SessionSegments a caller assigns to
GameplaySession.segments (or merges with existing ones) -- this module never
mutates the session itself, same "propose, don't apply" spirit as every other
suggestion-producing piece in this codebase (see GAME_RUN_AI_ASSIST_DESIGN.md
§3's human-review precedent).

Known limitation, spelled out rather than hidden (same spirit as
run_engine.py's own module docstring): a GameplaySession's `events` list is
one flat chronological stream merged across every pointer that was down
during the recording (see device_recorder.merge_gestures_into_events) -- two
genuinely concurrent touches (e.g. holding left while tapping jump) interleave
their PRESS/MOVE/RELEASE events by real time, not by pointer. This module
still classifies each pointer's own gesture correctly (a PRESS/RELEASE pair
is tracked per pointer_id, not by index adjacency), but the resulting
SessionSegments' index ranges can then overlap on the shared index axis --
GameplaySession.validate() already flags that as an "overlaps" warning, which
is the right place to surface it, not a special case here.
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


def classify_session(session: GameplaySession, regions: dict, on_log=None) -> list:
    """Returns SessionSegments for every gesture in `session.events` whose
    starting point (a TAP's own point, or a PRESS/RELEASE pair's PRESS point)
    falls inside some HudRegion in `regions` (dict[str, HudRegion], i.e.
    project.hud_regions). A gesture landing outside every region -- or a KEY
    event, which has no (x, y) at all -- produces no segment: left
    unclassified for raw replay or a human/future step to handle, never
    guessed at. Pure function: does not mutate `session`."""
    on_log = on_log or (lambda msg: None)
    region_list = list(regions.values())
    segments = []
    total_gestures = 0
    open_start: dict = {}   # pointer_id -> index of its open PRESS

    for i, event in enumerate(session.events):
        if event.kind == EventKind.TAP:
            total_gestures += 1
            if event.x is None or event.y is None:
                continue
            region = _best_region(region_list, event.x, event.y)
            if region is not None:
                segments.append(SessionSegment(
                    start_index=i, end_index=i + 1, action_name=region.action_name, label=region.name))
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
                segments.append(SessionSegment(
                    start_index=start, end_index=i + 1, action_name=region.action_name, label=region.name))

    segments.sort(key=lambda s: s.start_index)
    on_log(f"Classified {len(segments)} of {total_gestures} gesture(s) against {len(region_list)} HUD region(s) "
           f"({total_gestures - len(segments)} unmatched).")
    return segments
