"""SessionPlayer tests -- a fake connection stands in for LiveConnection,
same pattern tests/test_run_engine.py uses for GameRunExecutor. time.sleep is
patched so gap-timing assertions don't actually wait."""
import threading
import unittest
from unittest.mock import patch

from ..connection import FRAME_MS
from ..model import Action, EventKind, GameplaySession, PrimitiveEvent, SessionSegment
from ..session_replay import SessionPlayer


class FakeConnection:
    """Records every action it's asked to run, in call order. `skip_reason`,
    if given, is returned as a single (0, reason) skipped-event pair for
    every run_action call, to exercise the skipped-event logging path."""

    def __init__(self, skip_reason=None):
        self.calls = []
        self._lock = threading.Lock()
        self.skip_reason = skip_reason
        self.time_scale = 1.0

    def run_action(self, action: Action, ref_w: int, ref_h: int) -> list:
        with self._lock:
            self.calls.append(action)
        return [(0, self.skip_reason)] if self.skip_reason else []


def _events(kinds_and_frames) -> list:
    """Builds a flat event list from [(kind, frames), ...] -- frames only
    meaningful for EventKind.WAIT, ignored otherwise (matches PrimitiveEvent's
    own shape: `frames` is WAIT-only, see model.py)."""
    events = []
    for kind, frames in kinds_and_frames:
        if kind == EventKind.WAIT:
            events.append(PrimitiveEvent(kind=kind, frames=frames))
        else:
            events.append(PrimitiveEvent(kind=kind, x=0, y=0))
    return events


class ReplayRawTest(unittest.TestCase):
    def test_sends_all_events_as_one_action(self):
        events = _events([(EventKind.TAP, 0), (EventKind.WAIT, 5), (EventKind.TAP, 0)])
        session = GameplaySession(name="s", events=events)
        connection = FakeConnection()
        SessionPlayer(connection, ref_w=100, ref_h=200).replay_raw(session)
        self.assertEqual(len(connection.calls), 1)
        self.assertEqual(connection.calls[0].events, events)

    def test_logs_skipped_events(self):
        session = GameplaySession(name="s", events=_events([(EventKind.TAP, 0)]))
        connection = FakeConnection(skip_reason="not connected")
        logs = []
        SessionPlayer(connection, ref_w=100, ref_h=200, on_log=logs.append).replay_raw(session)
        self.assertTrue(any("skipped: not connected" in line for line in logs))


class ReplayClassifiedTest(unittest.TestCase):
    def test_runs_segments_in_start_index_order_even_if_unsorted(self):
        events = _events([(EventKind.TAP, 0)] * 6)
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=3, end_index=6, action_name="b"),
            SessionSegment(start_index=0, end_index=3, action_name="a"),
        ])
        actions = {"a": Action(name="a"), "b": Action(name="b")}
        connection = FakeConnection()
        with patch("irobot_gym_ide.session_replay.time.sleep"):
            SessionPlayer(connection, ref_w=100, ref_h=200).replay_classified(session, actions)
        self.assertEqual([a.name for a in connection.calls], ["a", "b"])

    def test_unknown_action_is_skipped_and_logged_not_raised(self):
        events = _events([(EventKind.TAP, 0)] * 3)
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=0, end_index=3, action_name="ghost"),
        ])
        connection = FakeConnection()
        logs = []
        with patch("irobot_gym_ide.session_replay.time.sleep"):
            SessionPlayer(connection, ref_w=100, ref_h=200, on_log=logs.append).replay_classified(session, {})
        self.assertEqual(connection.calls, [])
        self.assertTrue(any("unknown action" in line for line in logs))

    def test_no_segments_logs_and_does_not_call_connection(self):
        session = GameplaySession(name="s", events=_events([(EventKind.TAP, 0)]))
        connection = FakeConnection()
        logs = []
        SessionPlayer(connection, ref_w=100, ref_h=200, on_log=logs.append).replay_classified(session, {})
        self.assertEqual(connection.calls, [])
        self.assertTrue(any("no classified segments" in line for line in logs))

    def test_gap_between_segments_matches_recorded_wait_frames(self):
        # 10 WAIT frames sit strictly between segment "a" (events[0:1]) and
        # segment "b" (events[2:3]) -- the gap SessionPlayer should sleep for
        # before firing "b" is exactly those 10 frames, nothing else.
        events = _events([(EventKind.TAP, 0), (EventKind.WAIT, 10), (EventKind.TAP, 0)])
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=0, end_index=1, action_name="a"),
            SessionSegment(start_index=2, end_index=3, action_name="b"),
        ])
        actions = {"a": Action(name="a"), "b": Action(name="b")}
        connection = FakeConnection()
        slept = []
        with patch("irobot_gym_ide.session_replay.time.sleep", side_effect=slept.append):
            SessionPlayer(connection, ref_w=100, ref_h=200).replay_classified(session, actions)
        total_slept = sum(slept)
        self.assertAlmostEqual(total_slept, 10 * FRAME_MS / 1000.0, places=3)

    def test_action_shorter_than_recorded_span_gets_a_catchup_sleep(self):
        # the segment's real recorded span (events[0:3), a PRESS + WAIT(50) + RELEASE) took
        # 50 frames, but the classified action's own WAIT total is only 6 frames -- replay
        # should top up the missing 44 frames so overall pacing matches the real recording.
        events = _events([(EventKind.PRESS, 0), (EventKind.WAIT, 50), (EventKind.RELEASE, 0)])
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=0, end_index=3, action_name="right_jump"),
        ])
        actions = {"right_jump": Action(name="right_jump", events=[
            PrimitiveEvent(kind=EventKind.WAIT, frames=6),
        ])}
        connection = FakeConnection()
        slept = []
        with patch("irobot_gym_ide.session_replay.time.sleep", side_effect=slept.append):
            SessionPlayer(connection, ref_w=100, ref_h=200).replay_classified(session, actions)
        self.assertAlmostEqual(sum(slept), 44 * FRAME_MS / 1000.0, places=3)

    def test_catchup_is_logged(self):
        events = _events([(EventKind.PRESS, 0), (EventKind.WAIT, 50), (EventKind.RELEASE, 0)])
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=0, end_index=3, action_name="right_jump"),
        ])
        actions = {"right_jump": Action(name="right_jump")}
        connection = FakeConnection()
        logs = []
        with patch("irobot_gym_ide.session_replay.time.sleep"):
            SessionPlayer(connection, ref_w=100, ref_h=200, on_log=logs.append).replay_classified(
                session, actions)
        self.assertTrue(any("+50 frame(s) catch-up" in line for line in logs))

    def test_action_at_least_as_long_as_recorded_span_gets_no_catchup(self):
        events = _events([(EventKind.PRESS, 0), (EventKind.WAIT, 5), (EventKind.RELEASE, 0)])
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=0, end_index=3, action_name="a"),
        ])
        actions = {"a": Action(name="a", events=[PrimitiveEvent(kind=EventKind.WAIT, frames=20)])}
        connection = FakeConnection()
        slept = []
        with patch("irobot_gym_ide.session_replay.time.sleep", side_effect=slept.append):
            SessionPlayer(connection, ref_w=100, ref_h=200).replay_classified(session, actions)
        self.assertEqual(slept, [])

    def test_stop_halts_before_next_segment(self):
        events = _events([(EventKind.TAP, 0)] * 4)
        session = GameplaySession(name="s", events=events, segments=[
            SessionSegment(start_index=0, end_index=2, action_name="a"),
            SessionSegment(start_index=2, end_index=4, action_name="b"),
        ])
        actions = {"a": Action(name="a"), "b": Action(name="b")}
        connection = FakeConnection()
        player = SessionPlayer(connection, ref_w=100, ref_h=200)
        original_run_action = connection.run_action

        def run_action_then_stop(action, ref_w, ref_h):
            result = original_run_action(action, ref_w, ref_h)
            if action.name == "a":
                player.stop()
            return result

        connection.run_action = run_action_then_stop
        with patch("irobot_gym_ide.session_replay.time.sleep"):
            player.replay_classified(session, actions)
        self.assertEqual([a.name for a in connection.calls], ["a"])


if __name__ == "__main__":
    unittest.main()
