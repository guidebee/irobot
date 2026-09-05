"""Replays a saved GameplaySession against a live connection.

Two independent modes over the same saved file, mirroring the two audiences
model.GameplaySession's docstring describes:

  replay_raw        -- sends `session.events` in order, unmodified. Since a
                        session's events use the exact same PrimitiveEvent
                        vocabulary/WAIT-gap convention as an Action's, this is
                        just LiveConnection.run_action given a throwaway
                        Action wrapping them -- no new sending logic needed.
  replay_classified -- walks `session.segments` in recorded order, running
                        each one's named Action (looked up in the project's
                        own `actions`, not replayed from the session's raw
                        slice) with the real recorded gap timing between them
                        preserved. An unresolvable action_name logs and skips
                        that segment, same no-surprises "log and continue,
                        never raise" convention run_engine.py's node handlers
                        use -- a bad/stale classification shouldn't abort an
                        otherwise-fine replay.

                        replay_raw is the ground truth for how long things
                        actually took (it's literally the recorded stream), so
                        after running each segment's action, replay_classified
                        tops up with a "catch-up" sleep for the difference
                        between that segment's own real recorded span (model.
                        frames_between over [start_index, end_index)) and
                        however long the action's own WAIT events actually
                        took -- see hud_classifier.compare_replay_durations,
                        the classify-time diagnostic for this same gap; this
                        is the replay-time correction, so a session that
                        diagnostic flags still replays at roughly the right
                        pace instead of visibly drifting shorter (see
                        ACTION_CLASSIFICATION_DESIGN.md G10). Only tops up
                        (never trims) -- an action whose own script already
                        runs *longer* than the real recording isn't sped up,
                        since there's no way to un-spend time already used
                        running its real touch events.

Not itself Gym env stepping, same disclaimer run_engine.py's module docstring
makes for GameRun -- this is the IDE's own "replay it and watch the log" loop.
"""
from __future__ import annotations

import threading
import time

from .connection import FRAME_MS, LiveConnection
from .model import Action, EventKind, GameplaySession, frames_between as _frames_between


class SessionPlayer:
    def __init__(self, connection: LiveConnection, ref_w: int, ref_h: int, on_log=None):
        self.connection = connection
        self.ref_w = ref_w
        self.ref_h = ref_h
        self._on_log = on_log or (lambda msg: None)
        self._stop = threading.Event()

    def stop(self) -> None:
        """Requests replay wind down after the event/segment currently in
        flight finishes. Idempotent; safe to call from any thread."""
        self._stop.set()

    def replay_raw(self, session: GameplaySession) -> None:
        self._stop.clear()
        self._on_log(f"Replaying session {session.name!r} raw ({len(session.events)} event(s))...")
        action = Action(name=f"__session_raw__:{session.name}", events=session.events)
        skipped = self.connection.run_action(action, self.ref_w, self.ref_h)
        for i, reason in skipped:
            self._on_log(f"  event {i} skipped: {reason}")
        self._on_log(f"Replayed session {session.name!r} raw.")

    def replay_classified(self, session: GameplaySession, project_actions: dict) -> None:
        self._stop.clear()
        segments = sorted(session.segments, key=lambda s: s.start_index)
        if not segments:
            self._on_log(f"Session {session.name!r} has no classified segments -- nothing to replay.")
            return
        self._on_log(f"Replaying session {session.name!r} classified ({len(segments)} segment(s))...")
        prev_end = 0
        for seg in segments:
            if self._stop.is_set():
                break
            gap_frames = _frames_between(session.events, prev_end, seg.start_index)
            self._sleep_frames(gap_frames)
            if self._stop.is_set():
                break
            desc = f"{seg.label!r} ({seg.action_name!r})" if seg.label else repr(seg.action_name)
            action = project_actions.get(seg.action_name)
            if action is None:
                self._on_log(f"  segment {desc}: unknown action, skipped")
                prev_end = seg.end_index
                continue
            skipped = self.connection.run_action(action, self.ref_w, self.ref_h)
            if skipped:
                reasons = "; ".join(f"event {i}: {reason}" for i, reason in skipped)
                note = f" ({len(skipped)} event(s) skipped -- {reasons})"
            else:
                note = ""
            recorded_frames = _frames_between(session.events, seg.start_index, seg.end_index)
            action_frames = sum(e.frames for e in action.events if e.kind == EventKind.WAIT)
            catchup = recorded_frames - action_frames
            if catchup > 0 and not self._stop.is_set():
                self._sleep_frames(catchup)
                note += f" (+{catchup} frame(s) catch-up to match the real recorded duration)"
            self._on_log(f"  segment {desc}: ran action{note}")
            prev_end = seg.end_index
        self._on_log(f"Replayed session {session.name!r} classified.")

    def _sleep_frames(self, frames: int) -> None:
        remaining = frames * FRAME_MS * self.connection.time_scale / 1000.0
        step = 0.05
        while remaining > 0 and not self._stop.is_set():
            time.sleep(min(step, remaining))
            remaining -= step
