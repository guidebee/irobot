"""Pure model tests -- no Qt, no socket, no device. Run with:
    python -m unittest discover -s irobot_gym_ide/tests
(or via pytest, which auto-discovers unittest.TestCase classes too)."""
import unittest

from ..model import (
    Action, EventKind, GameRun, PrimitiveEvent, Project, RunEdge, RunNode, RunNodeKind,
    conflicting_pointer_actions, orphan_releases,
)


class PrimitiveEventRoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_zero_valued_position(self):
        # regression case: an earlier to_dict() implementation dropped x=0/y=0
        # because it treated "falsy" as "default, omit" -- (0, 0) is a real
        # corner-of-screen coordinate, not an absent one.
        event = PrimitiveEvent(kind=EventKind.TAP, x=0, y=0)
        restored = PrimitiveEvent.from_dict(event.to_dict())
        self.assertEqual(restored.x, 0)
        self.assertEqual(restored.y, 0)

    def test_round_trip_key_event(self):
        event = PrimitiveEvent(kind=EventKind.KEY, key_name="back")
        restored = PrimitiveEvent.from_dict(event.to_dict())
        self.assertEqual(restored.key_name, "back")
        self.assertIsNone(restored.keycode)


class ActionValidateTest(unittest.TestCase):
    def test_lone_release_does_not_warn(self):
        # the idiomatic "stop" half of a split start/stop action pair (see
        # examples/mario_platformer.yaml's move_left_stop) -- validate() has
        # no way to know a PRESS exists in a sibling action, so it must not
        # flag this locally; orphan_releases() is the project-wide check.
        action = Action(name="move_left_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0)])
        self.assertEqual(action.validate(), [])

    def test_lone_move_does_not_warn(self):
        action = Action(name="drag_continue", events=[PrimitiveEvent(kind=EventKind.MOVE, x=5, y=5, pointer_id=0)])
        self.assertEqual(action.validate(), [])

    def test_press_then_release_is_clean(self):
        action = Action(name="tap_and_hold", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=10, y=20, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
        ])
        self.assertEqual(action.validate(), [])

    def test_double_press_without_release_warns(self):
        action = Action(name="bad", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1, pointer_id=0),
            PrimitiveEvent(kind=EventKind.PRESS, x=2, y=2, pointer_id=0),
        ])
        warnings = action.validate()
        self.assertTrue(any("already held" in w for w in warnings))

    def test_tap_missing_position_warns(self):
        action = Action(name="bad", events=[PrimitiveEvent(kind=EventKind.TAP)])
        warnings = action.validate()
        self.assertTrue(any("no (x, y)" in w for w in warnings))


class ConflictingPointerActionsTest(unittest.TestCase):
    def test_two_hold_actions_sharing_a_pointer_are_reported(self):
        actions = {
            "left": Action(name="left", events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1, pointer_id=0)]),
            "right": Action(name="right", events=[PrimitiveEvent(kind=EventKind.PRESS, x=2, y=2, pointer_id=0)]),
        }
        conflicts = conflicting_pointer_actions(actions)
        self.assertEqual(len(conflicts), 1)
        pointer_id, names = conflicts[0]
        self.assertEqual(pointer_id, 0)
        self.assertEqual(set(names), {"left", "right"})

    def test_press_then_release_in_same_action_is_not_reported(self):
        actions = {
            "tap_and_hold": Action(name="tap_and_hold", events=[
                PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1, pointer_id=0),
                PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
            ]),
            "other": Action(name="other", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5, pointer_id=1)]),
        }
        self.assertEqual(conflicting_pointer_actions(actions), [])


class OrphanReleasesTest(unittest.TestCase):
    def test_split_start_stop_pair_is_not_orphaned(self):
        actions = {
            "move_left_start": Action(name="move_left_start",
                                       events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1, pointer_id=0)]),
            "move_left_stop": Action(name="move_left_stop",
                                      events=[PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0)]),
        }
        self.assertEqual(orphan_releases(actions), [])

    def test_release_with_no_press_anywhere_is_orphaned(self):
        actions = {
            "stop": Action(name="stop", events=[PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=3)]),
        }
        self.assertEqual(orphan_releases(actions), [("stop", 3)])


class ProjectRoundTripTest(unittest.TestCase):
    def test_actions_survive_to_dict_from_dict(self):
        project = Project(name="game", reference_width=1080, reference_height=2400)
        project.add_action(Action(name="jump", events=[
            PrimitiveEvent(kind=EventKind.TAP, x=900, y=800, pointer_id=1),
        ]))
        restored = Project.from_dict(project.to_dict())
        self.assertEqual(restored.name, "game")
        self.assertEqual(restored.reference_width, 1080)
        self.assertIn("jump", restored.actions)
        self.assertEqual(restored.actions["jump"].events[0].x, 900)

    def test_runs_survive_to_dict_from_dict(self):
        project = Project(name="game")
        run = GameRun(name="main")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="jump"))
        run.add_node(RunNode(id="d", kind=RunNodeKind.DELAY, frames=5))
        run.add_edge(RunEdge(id="e1", source="a", target="d"))
        project.add_run(run)
        restored = Project.from_dict(project.to_dict())
        self.assertIn("main", restored.runs)
        restored_run = restored.runs["main"]
        self.assertEqual(restored_run.nodes["a"].action_name, "jump")
        self.assertEqual(restored_run.nodes["d"].frames, 5)
        self.assertEqual(len(restored_run.edges), 1)
        self.assertEqual(restored_run.edges[0].via, "out")


class GameRunGraphTest(unittest.TestCase):
    def test_roots_are_nodes_with_no_incoming_edge(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="c", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="a", target="c"))
        self.assertEqual(set(run.roots()), {"a", "b"})

    def test_remove_node_also_removes_its_edges(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="a", target="b"))
        run.remove_node("a")
        self.assertEqual(run.edges, [])

    def test_validate_flags_unknown_action_reference(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="missing"))
        warnings = run.validate(project_actions={})
        self.assertTrue(any("unknown action" in w for w in warnings))

    def test_validate_flags_via_on_non_repeat_source(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="a", target="b", via="body"))
        warnings = run.validate(project_actions={})
        self.assertTrue(any("only valid from a repeat node" in w for w in warnings))

    def test_validate_flags_repeat_with_two_body_edges(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="r1", kind=RunNodeKind.REPEAT, times=3))
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="r1", target="a", via="body"))
        run.add_edge(RunEdge(id="e2", source="r1", target="b", via="body"))
        warnings = run.validate(project_actions={})
        self.assertTrue(any("more than one body connection" in w for w in warnings))

    def test_clean_graph_has_no_warnings(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="jump"))
        run.add_node(RunNode(id="rep", kind=RunNodeKind.REPEAT, times=2))
        run.add_node(RunNode(id="body", kind=RunNodeKind.DELAY, frames=5))
        run.add_node(RunNode(id="after", kind=RunNodeKind.ACTION, action_name="jump"))
        run.add_edge(RunEdge(id="e1", source="a", target="rep"))
        run.add_edge(RunEdge(id="e2", source="rep", target="body", via="body"))
        run.add_edge(RunEdge(id="e3", source="rep", target="after", via="after"))
        self.assertEqual(run.validate(project_actions={"jump": object()}), [])


if __name__ == "__main__":
    unittest.main()
