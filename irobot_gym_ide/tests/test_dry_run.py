"""DryRunConnection tests, plus its actual use through GameRunExecutor/SessionPlayer -- the
whole point is that neither needed any code changes to support a dry run, so these exercise
the real executors, not just DryRunConnection in isolation."""
import unittest
from unittest.mock import patch

from ..dry_run import DryRunConnection
from ..model import Action, EventKind, GameRun, GameplaySession, PrimitiveEvent, RunEdge, RunNode, RunNodeKind, \
    SessionSegment
from ..run_engine import GameRunExecutor
from ..session_replay import SessionPlayer


class DryRunConnectionTest(unittest.TestCase):
    def test_run_action_logs_each_event_and_sends_nothing(self):
        logs = []
        conn = DryRunConnection(on_log=logs.append)
        action = Action(name="jump", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=9, pointer_id=1),
            PrimitiveEvent(kind=EventKind.WAIT, frames=10),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
        ])
        skipped = conn.run_action(action, ref_w=100, ref_h=100)
        self.assertEqual(skipped, [])
        self.assertTrue(any("PRESS pointer=1 (5, 9)" in line for line in logs))
        self.assertTrue(any("WAIT 10 frame(s)" in line for line in logs))
        self.assertTrue(any("RELEASE pointer=1" in line for line in logs))

    def test_latest_frame_is_always_none(self):
        self.assertIsNone(DryRunConnection().latest_frame())

    def test_default_time_scale_is_one(self):
        self.assertEqual(DryRunConnection().time_scale, 1.0)


class GameRunExecutorDryRunTest(unittest.TestCase):
    def test_action_and_delay_run_end_to_end_with_no_device(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="jump"))
        run.add_node(RunNode(id="d", kind=RunNodeKind.DELAY, frames=1))
        run.add_edge(RunEdge(id="e1", source="a", target="d"))
        actions = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=1, y=1)])}
        logs = []
        conn = DryRunConnection(time_scale=0.01, on_log=logs.append)
        executor = GameRunExecutor(conn, actions, ref_w=100, ref_h=100, on_log=logs.append)
        with patch("irobot_gym_ide.run_engine.time.sleep"):
            executor.run(run)
        self.assertTrue(any("ran action 'jump'" in line for line in logs))
        self.assertTrue(any("TAP pointer=0 (1, 1)" in line for line in logs))

    def test_compare_node_always_takes_no_match_with_no_frame(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="hp_full"))
        run.add_node(RunNode(id="m", kind=RunNodeKind.ACTION, action_name="on_match"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_no_match"))
        run.add_edge(RunEdge(id="e1", source="c", target="m", via="match"))
        run.add_edge(RunEdge(id="e2", source="c", target="n", via="no_match"))
        actions = {name: Action(name=name) for name in ("on_match", "on_no_match")}
        logs = []
        executor = GameRunExecutor(DryRunConnection(), actions, ref_w=100, ref_h=100,
                                    templates={"hp_full": object()}, on_log=logs.append)
        executor.run(run)
        self.assertTrue(any("no live frame available yet, treated as no_match" in line for line in logs))


class SessionPlayerDryRunTest(unittest.TestCase):
    def test_replay_classified_runs_with_no_device(self):
        events = [PrimitiveEvent(kind=EventKind.TAP, x=1, y=1)]
        session = GameplaySession(name="s", events=events,
                                   segments=[SessionSegment(start_index=0, end_index=1, action_name="jump")])
        actions = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=1, y=1)])}
        logs = []
        conn = DryRunConnection(time_scale=0.01, on_log=logs.append)
        with patch("irobot_gym_ide.session_replay.time.sleep"):
            SessionPlayer(conn, ref_w=100, ref_h=100, on_log=logs.append).replay_classified(session, actions)
        self.assertTrue(any("ran action" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
