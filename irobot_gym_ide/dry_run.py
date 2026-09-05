"""A connection stand-in that logs what it WOULD send instead of actually sending anything --
lets a human preview a GameRun's or Action's sequence and pacing with no device attached (see
ACTION_CLASSIFICATION_DESIGN.md G15). GameRunExecutor and SessionPlayer only ever need
`run_action`/`latest_frame`/`time_scale` from whatever `connection` they're given, so both work
completely unchanged against this -- no new "dry run mode" flag anywhere in either, just a
different object passed in (see gui/main_window.py's `_preview_game_run`/`_preview_action`).

COMPARE/FIND_TEMPLATE/ASSERT nodes can't be evaluated without a real frame -- `latest_frame()`
always returns None here, so those always take their "no_match"/"not_found" branch (COMPARE/
FIND_TEMPLATE) or record a FAIL (ASSERT); each of those already logs clearly when that happens
(see run_engine.py's _run_compare/_run_find_template/_run_assert), so a human previewing a run
isn't left confused by a branch that never fires here but might for real. DELAY/WAIT durations
still really sleep (scaled by `time_scale`, exactly like a live connection), so a preview's
pacing matches what a real run would feel like -- pass a small `time_scale` for a fast,
structure-only preview instead of a paced one.
"""
from __future__ import annotations

from .model import Action, EventKind, PrimitiveEvent


def _describe(event: PrimitiveEvent) -> str:
    if event.kind == EventKind.WAIT:
        return f"WAIT {event.frames} frame(s)"
    if event.kind == EventKind.KEY:
        return f"KEY {event.key_name or event.keycode}"
    pos = f"({event.x}, {event.y})" if event.x is not None and event.y is not None else "(no position)"
    return f"{event.kind.value.upper()} pointer={event.pointer_id} {pos}"


class DryRunConnection:
    """Duck-types just enough of LiveConnection for GameRunExecutor/SessionPlayer: `run_action`,
    `latest_frame`, `time_scale`. Never touches a socket."""

    def __init__(self, time_scale: float = 1.0, on_log=None):
        self.time_scale = time_scale
        self._on_log = on_log or (lambda msg: None)

    def run_action(self, action: Action, ref_w: int, ref_h: int) -> list:
        """Logs what each of `action`'s events would have done; sends nothing. Always
        returns an empty skipped-list -- there's no live held-pointer state here to violate,
        so nothing is ever "skipped" the way a real connection might skip one."""
        for event in action.events:
            self._on_log(f"    [dry run] {_describe(event)}")
        return []

    def latest_frame(self):
        return None
