"""GameRunExecutor tests -- a fake connection stands in for LiveConnection so
these run with no socket/device, just like the rest of this package's model
tests. Parallel branches are asserted by set membership (order between
concurrent branches is intentionally unspecified), sequential/join ordering
by exact call order."""
import threading
import time
import unittest

from ..model import Action, GameRun, RunEdge, RunNode, RunNodeKind
from ..run_engine import GameRunExecutor

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class FakeConnection:
    """Records every action name it's asked to run, in the order runs
    actually started (not finished) -- good enough to assert both strict
    sequencing and "these ran concurrently" without depending on wall-clock
    timing. `frame`, if given, is what latest_frame() returns -- for COMPARE
    node tests, which need a live frame to crop and compare."""

    def __init__(self, delay: float = 0.0, frame=None):
        self.delay = delay
        self.calls = []
        self._lock = threading.Lock()
        self._frame = frame

    def run_action(self, action: Action, ref_w: int, ref_h: int) -> list:
        with self._lock:
            self.calls.append(action.name)
        if self.delay:
            time.sleep(self.delay)
        return []

    def latest_frame(self):
        return self._frame


def _executor(connection, actions) -> GameRunExecutor:
    return GameRunExecutor(connection, actions, ref_w=1080, ref_h=2400)


class SequentialRunTest(unittest.TestCase):
    def test_chain_runs_in_order(self):
        actions = {name: Action(name=name) for name in ("a", "b", "c")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="n1", kind=RunNodeKind.ACTION, action_name="a"))
        run.add_node(RunNode(id="n2", kind=RunNodeKind.ACTION, action_name="b"))
        run.add_node(RunNode(id="n3", kind=RunNodeKind.ACTION, action_name="c"))
        run.add_edge(RunEdge(id="e1", source="n1", target="n2"))
        run.add_edge(RunEdge(id="e2", source="n2", target="n3"))

        connection = FakeConnection()
        _executor(connection, actions).run(run)
        self.assertEqual(connection.calls, ["a", "b", "c"])


class ForkJoinTest(unittest.TestCase):
    def test_fork_runs_both_branches_before_join_node(self):
        actions = {name: Action(name=name) for name in ("start", "left", "right", "end")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="s", kind=RunNodeKind.ACTION, action_name="start"))
        run.add_node(RunNode(id="l", kind=RunNodeKind.ACTION, action_name="left"))
        run.add_node(RunNode(id="rt", kind=RunNodeKind.ACTION, action_name="right"))
        run.add_node(RunNode(id="e", kind=RunNodeKind.ACTION, action_name="end"))
        run.add_edge(RunEdge(id="e1", source="s", target="l"))
        run.add_edge(RunEdge(id="e2", source="s", target="rt"))
        run.add_edge(RunEdge(id="e3", source="l", target="e"))
        run.add_edge(RunEdge(id="e4", source="rt", target="e"))

        connection = FakeConnection(delay=0.02)
        _executor(connection, actions).run(run)
        # start first, end last, left/right in between in either order (join waits for both)
        self.assertEqual(connection.calls[0], "start")
        self.assertEqual(connection.calls[-1], "end")
        self.assertEqual(set(connection.calls[1:3]), {"left", "right"})

    def test_multiple_roots_all_start(self):
        actions = {name: Action(name=name) for name in ("a", "b")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="a"))
        run.add_node(RunNode(id="b", kind=RunNodeKind.ACTION, action_name="b"))

        connection = FakeConnection()
        _executor(connection, actions).run(run)
        self.assertEqual(set(connection.calls), {"a", "b"})


class RepeatTest(unittest.TestCase):
    def test_repeat_runs_body_n_times_then_after_once(self):
        actions = {name: Action(name=name) for name in ("before", "body", "after")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="b0", kind=RunNodeKind.ACTION, action_name="before"))
        run.add_node(RunNode(id="rep", kind=RunNodeKind.REPEAT, times=3))
        run.add_node(RunNode(id="body", kind=RunNodeKind.ACTION, action_name="body"))
        run.add_node(RunNode(id="after", kind=RunNodeKind.ACTION, action_name="after"))
        run.add_edge(RunEdge(id="e1", source="b0", target="rep"))
        run.add_edge(RunEdge(id="e2", source="rep", target="body", via="body"))
        run.add_edge(RunEdge(id="e3", source="rep", target="after", via="after"))

        connection = FakeConnection()
        _executor(connection, actions).run(run)
        self.assertEqual(connection.calls, ["before", "body", "body", "body", "after"])

    def test_repeat_with_no_after_edge_just_stops(self):
        actions = {"body": Action(name="body")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="rep", kind=RunNodeKind.REPEAT, times=2))
        run.add_node(RunNode(id="body", kind=RunNodeKind.ACTION, action_name="body"))
        run.add_edge(RunEdge(id="e1", source="rep", target="body", via="body"))

        connection = FakeConnection()
        _executor(connection, actions).run(run)
        self.assertEqual(connection.calls, ["body", "body"])

    def test_nested_repeat(self):
        actions = {"inner": Action(name="inner")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="outer", kind=RunNodeKind.REPEAT, times=2))
        run.add_node(RunNode(id="inner_rep", kind=RunNodeKind.REPEAT, times=3))
        run.add_node(RunNode(id="inner", kind=RunNodeKind.ACTION, action_name="inner"))
        run.add_edge(RunEdge(id="e1", source="outer", target="inner_rep", via="body"))
        run.add_edge(RunEdge(id="e2", source="inner_rep", target="inner", via="body"))

        connection = FakeConnection()
        _executor(connection, actions).run(run)
        self.assertEqual(connection.calls, ["inner"] * 6)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class CompareTest(unittest.TestCase):
    def _template_and_frame(self):
        from ..model import ImageTemplate
        frame = np.zeros((50, 100), dtype=np.uint8)
        frame[10:30, 10:40] = 200
        template = ImageTemplate.capture(
            "hp_full", x=10, y=10, width=30, height=20,
            frame_w=100, frame_h=50, frame=frame, ref_res_w=100, ref_res_h=50)
        return template, frame

    def _run(self, run, actions, templates, connection):
        executor = GameRunExecutor(connection, actions, ref_w=100, ref_h=50, templates=templates)
        executor.run(run)
        return executor

    def test_match_fires_match_edge_only(self):
        template, frame = self._template_and_frame()
        actions = {name: Action(name=name) for name in ("on_match", "on_no_match")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="hp_full"))
        run.add_node(RunNode(id="m", kind=RunNodeKind.ACTION, action_name="on_match"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_no_match"))
        run.add_edge(RunEdge(id="e1", source="c", target="m", via="match"))
        run.add_edge(RunEdge(id="e2", source="c", target="n", via="no_match"))

        connection = FakeConnection(frame=(100, 50, frame))
        self._run(run, actions, {"hp_full": template}, connection)
        self.assertEqual(connection.calls, ["on_match"])

    def test_no_match_fires_no_match_edge_only(self):
        template, _ = self._template_and_frame()
        empty_frame = np.zeros((50, 100), dtype=np.uint8)
        actions = {name: Action(name=name) for name in ("on_match", "on_no_match")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="hp_full"))
        run.add_node(RunNode(id="m", kind=RunNodeKind.ACTION, action_name="on_match"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_no_match"))
        run.add_edge(RunEdge(id="e1", source="c", target="m", via="match"))
        run.add_edge(RunEdge(id="e2", source="c", target="n", via="no_match"))

        connection = FakeConnection(frame=(100, 50, empty_frame))
        self._run(run, actions, {"hp_full": template}, connection)
        self.assertEqual(connection.calls, ["on_no_match"])

    def test_unknown_template_is_treated_as_no_match(self):
        actions = {"on_no_match": Action(name="on_no_match")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="ghost"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_no_match"))
        run.add_edge(RunEdge(id="e1", source="c", target="n", via="no_match"))

        connection = FakeConnection()
        logs = []
        executor = GameRunExecutor(connection, actions, ref_w=100, ref_h=50, templates={}, on_log=logs.append)
        executor.run(run)
        self.assertEqual(connection.calls, ["on_no_match"])
        self.assertTrue(any("unknown template" in line for line in logs))


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class FindTemplateTest(unittest.TestCase):
    def _template_and_frame(self):
        from ..model import ImageTemplate
        frame = np.zeros((50, 100), dtype=np.uint8)
        frame[10:30, 10:40] = 200
        template = ImageTemplate.capture(
            "coin", x=10, y=10, width=30, height=20,
            frame_w=100, frame_h=50, frame=frame, ref_res_w=100, ref_res_h=50)
        return template, frame

    def test_found_fires_found_edge_and_stashes_coordinate(self):
        template, frame = self._template_and_frame()
        actions = {name: Action(name=name) for name in ("on_found", "on_not_found")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="f", kind=RunNodeKind.FIND_TEMPLATE, template_name="coin"))
        run.add_node(RunNode(id="m", kind=RunNodeKind.ACTION, action_name="on_found"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_not_found"))
        run.add_edge(RunEdge(id="e1", source="f", target="m", via="found"))
        run.add_edge(RunEdge(id="e2", source="f", target="n", via="not_found"))

        connection = FakeConnection(frame=(100, 50, frame))
        executor = GameRunExecutor(connection, actions, ref_w=100, ref_h=50, templates={"coin": template})
        executor.run(run)
        self.assertEqual(connection.calls, ["on_found"])
        self.assertIn("f", executor.last_found)
        x, y = executor.last_found["f"]
        self.assertAlmostEqual(x, 10, delta=2)
        self.assertAlmostEqual(y, 10, delta=2)

    def test_not_found_fires_not_found_edge_only(self):
        template, _ = self._template_and_frame()
        empty_frame = np.zeros((50, 100), dtype=np.uint8)
        actions = {name: Action(name=name) for name in ("on_found", "on_not_found")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="f", kind=RunNodeKind.FIND_TEMPLATE, template_name="coin"))
        run.add_node(RunNode(id="m", kind=RunNodeKind.ACTION, action_name="on_found"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_not_found"))
        run.add_edge(RunEdge(id="e1", source="f", target="m", via="found"))
        run.add_edge(RunEdge(id="e2", source="f", target="n", via="not_found"))

        connection = FakeConnection(frame=(100, 50, empty_frame))
        executor = GameRunExecutor(connection, actions, ref_w=100, ref_h=50, templates={"coin": template})
        executor.run(run)
        self.assertEqual(connection.calls, ["on_not_found"])
        self.assertNotIn("f", executor.last_found)

    def test_unknown_template_is_treated_as_not_found(self):
        actions = {"on_not_found": Action(name="on_not_found")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="f", kind=RunNodeKind.FIND_TEMPLATE, template_name="ghost"))
        run.add_node(RunNode(id="n", kind=RunNodeKind.ACTION, action_name="on_not_found"))
        run.add_edge(RunEdge(id="e1", source="f", target="n", via="not_found"))

        connection = FakeConnection()
        logs = []
        executor = GameRunExecutor(connection, actions, ref_w=100, ref_h=50, templates={}, on_log=logs.append)
        executor.run(run)
        self.assertEqual(connection.calls, ["on_not_found"])
        self.assertTrue(any("unknown template" in line for line in logs))


class StopTest(unittest.TestCase):
    def test_stop_halts_before_later_nodes(self):
        # a chain of 3; stop() fires (from run_action itself, simulating a
        # user clicking Stop mid-run) right after node "a" completes -- "b"
        # and "c" must never run.
        actions = {name: Action(name=name) for name in ("a", "b", "c")}
        run = GameRun(name="r")
        run.add_node(RunNode(id="n1", kind=RunNodeKind.ACTION, action_name="a"))
        run.add_node(RunNode(id="n2", kind=RunNodeKind.ACTION, action_name="b"))
        run.add_node(RunNode(id="n3", kind=RunNodeKind.ACTION, action_name="c"))
        run.add_edge(RunEdge(id="e1", source="n1", target="n2"))
        run.add_edge(RunEdge(id="e2", source="n2", target="n3"))

        connection = FakeConnection()
        executor = _executor(connection, actions)
        original_run_action = connection.run_action

        def run_action_then_stop(action, ref_w, ref_h):
            result = original_run_action(action, ref_w, ref_h)
            if action.name == "a":
                executor.stop()
            return result

        connection.run_action = run_action_then_stop
        executor.run(run)
        self.assertEqual(connection.calls, ["a"])


class UnknownActionTest(unittest.TestCase):
    def test_unknown_action_reference_is_skipped_not_raised(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="n1", kind=RunNodeKind.ACTION, action_name="ghost"))
        connection = FakeConnection()
        logs = []
        executor = GameRunExecutor(connection, actions={}, ref_w=1080, ref_h=2400, on_log=logs.append)
        executor.run(run)
        self.assertEqual(connection.calls, [])
        self.assertTrue(any("unknown action" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
