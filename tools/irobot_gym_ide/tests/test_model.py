"""Pure model tests -- no Qt, no socket, no device. Run with:
    python -m unittest discover -s tools/irobot_gym_ide/tests
(or via pytest, which auto-discovers unittest.TestCase classes too)."""
import unittest

from ..model import (
    Action, EventKind, PrimitiveEvent, Project, conflicting_pointer_actions, orphan_releases,
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


if __name__ == "__main__":
    unittest.main()
