"""Pure model tests -- no Qt, no socket, no device. Run with:
    python -m unittest discover -s irobot_gym_ide/tests
(or via pytest, which auto-discovers unittest.TestCase classes too)."""
import base64
import unittest

from ..model import (
    Action, ActionKind, EventKind, GameRun, HudRegion, HudRegionCombo, ImageTemplate, PrimitiveEvent, Project,
    RunEdge, RunNode, RunNodeKind, SessionSegment, classified_pointer_conflicts, conflicting_pointer_actions,
    events_look_alike, find_matching_action, orphan_releases, run_pointer_conflicts, scale_point,
)

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class ScalePointTest(unittest.TestCase):
    def test_scales_proportionally_into_target_resolution(self):
        # halfway across/down a 1000x2000 reference should land halfway across/down 500x1000
        self.assertEqual(scale_point(500, 1000, 1000, 2000, 500, 1000), (250, 500))

    def test_identity_when_target_equals_reference(self):
        self.assertEqual(scale_point(123, 456, 1080, 2400, 1080, 2400), (123, 456))

    def test_falls_back_to_identity_when_reference_size_is_zero(self):
        self.assertEqual(scale_point(123, 456, 0, 0, 1440, 3200), (123, 456))

    def test_scales_independently_per_axis(self):
        # a target with a different aspect ratio than the reference -- each axis scales
        # by its own ratio, no attempt to preserve aspect ratio or letterbox.
        self.assertEqual(scale_point(100, 100, 100, 100, 300, 50), (300, 50))


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


class ActionKindTest(unittest.TestCase):
    def test_lone_press_infers_hold_start(self):
        action = Action(name="right_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1)])
        self.assertEqual(action.infer_kind(), ActionKind.HOLD_START)
        self.assertEqual(action.effective_kind, ActionKind.HOLD_START)

    def test_lone_release_infers_hold_stop(self):
        action = Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)])
        self.assertEqual(action.infer_kind(), ActionKind.HOLD_STOP)

    def test_single_tap_infers_momentary(self):
        action = Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=1, y=1)])
        self.assertEqual(action.infer_kind(), ActionKind.MOMENTARY)

    def test_press_release_pair_infers_momentary(self):
        action = Action(name="tap_and_hold", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ])
        self.assertEqual(action.infer_kind(), ActionKind.MOMENTARY)

    def test_multi_pointer_sequence_infers_macro(self):
        action = Action(name="right_jump", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1, pointer_id=0),
            PrimitiveEvent(kind=EventKind.PRESS, x=2, y=2, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
        ])
        self.assertEqual(action.infer_kind(), ActionKind.MACRO)

    def test_wait_events_dont_affect_inference(self):
        action = Action(name="jump", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1),
            PrimitiveEvent(kind=EventKind.WAIT, frames=10),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ])
        self.assertEqual(action.infer_kind(), ActionKind.MOMENTARY)

    def test_explicit_kind_overrides_inference(self):
        action = Action(name="right_jump", kind=ActionKind.MACRO, events=[
            PrimitiveEvent(kind=EventKind.TAP, x=1, y=1),
        ])
        self.assertEqual(action.infer_kind(), ActionKind.MOMENTARY)
        self.assertEqual(action.effective_kind, ActionKind.MACRO)

    def test_kind_round_trips_through_to_dict_from_dict(self):
        action = Action(name="right_start", kind=ActionKind.HOLD_START,
                         events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1)])
        restored = Action.from_dict(action.to_dict())
        self.assertEqual(restored.kind, ActionKind.HOLD_START)

    def test_unset_kind_is_omitted_from_to_dict(self):
        action = Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=1, y=1)])
        self.assertNotIn("kind", action.to_dict())
        restored = Action.from_dict(action.to_dict())
        self.assertIsNone(restored.kind)


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


class ClassifiedPointerConflictsTest(unittest.TestCase):
    def test_flags_a_tap_action_sharing_a_pointer_with_a_still_open_hold(self):
        # right_start holds pointer 0; jump (authored on the same default pointer_id 0)
        # fires while it's still held -- jump's own RELEASE would end the hold early.
        actions = {
            "right_start": Action(name="right_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1)]),
            "right_stop": Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)]),
            "jump": Action(name="jump", events=[
                PrimitiveEvent(kind=EventKind.PRESS, x=9, y=9),
                PrimitiveEvent(kind=EventKind.RELEASE),
            ]),
        }
        segments = [
            SessionSegment(start_index=0, end_index=1, action_name="right_start"),
            SessionSegment(start_index=1, end_index=2, action_name="jump"),
            SessionSegment(start_index=2, end_index=3, action_name="right_stop"),
        ]
        warnings = classified_pointer_conflicts(segments, actions)
        self.assertEqual(len(warnings), 1)
        self.assertIn("right_start", warnings[0])
        self.assertIn("pointer 0", warnings[0])

    def test_different_pointer_ids_are_not_flagged(self):
        actions = {
            "right_start": Action(name="right_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1)]),
            "right_stop": Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)]),
            "jump": Action(name="jump", events=[
                PrimitiveEvent(kind=EventKind.PRESS, x=9, y=9, pointer_id=1),
                PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
            ]),
        }
        segments = [
            SessionSegment(start_index=0, end_index=1, action_name="right_start"),
            SessionSegment(start_index=1, end_index=2, action_name="jump"),
            SessionSegment(start_index=2, end_index=3, action_name="right_stop"),
        ]
        self.assertEqual(classified_pointer_conflicts(segments, actions), [])

    def test_sequential_non_overlapping_use_of_the_same_pointer_is_not_flagged(self):
        actions = {
            "right_start": Action(name="right_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1)]),
            "right_stop": Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)]),
        }
        segments = [
            SessionSegment(start_index=0, end_index=1, action_name="right_start"),
            SessionSegment(start_index=1, end_index=2, action_name="right_stop"),
            SessionSegment(start_index=2, end_index=3, action_name="right_start"),
            SessionSegment(start_index=3, end_index=4, action_name="right_stop"),
        ]
        self.assertEqual(classified_pointer_conflicts(segments, actions), [])

    def test_unknown_action_name_is_skipped_not_raised(self):
        segments = [SessionSegment(start_index=0, end_index=1, action_name="missing")]
        self.assertEqual(classified_pointer_conflicts(segments, {}), [])


class RunPointerConflictsTest(unittest.TestCase):
    def _actions(self):
        return {
            "right_start": Action(name="right_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=1, y=1)]),
            "right_stop": Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)]),
            "jump": Action(name="jump", events=[
                PrimitiveEvent(kind=EventKind.PRESS, x=9, y=9),
                PrimitiveEvent(kind=EventKind.RELEASE),
            ]),
            "jump_other_pointer": Action(name="jump_other_pointer", events=[
                PrimitiveEvent(kind=EventKind.PRESS, x=9, y=9, pointer_id=1),
                PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
            ]),
        }

    def _chain(self, *action_names):
        run = GameRun(name="r")
        for i, name in enumerate(action_names):
            run.add_node(RunNode(id=f"n{i}", kind=RunNodeKind.ACTION, action_name=name))
        for i in range(len(action_names) - 1):
            run.add_edge(RunEdge(id=f"e{i}", source=f"n{i}", target=f"n{i + 1}"))
        return run

    def test_sequential_chain_with_same_pointer_conflict_is_flagged(self):
        run = self._chain("right_start", "jump", "right_stop")
        warnings = run_pointer_conflicts(run, self._actions())
        self.assertEqual(len(warnings), 1)
        self.assertIn("right_start", warnings[0])
        self.assertIn("pointer 0", warnings[0])

    def test_sequential_chain_with_different_pointer_is_not_flagged(self):
        run = self._chain("right_start", "jump_other_pointer", "right_stop")
        self.assertEqual(run_pointer_conflicts(run, self._actions()), [])

    def test_release_before_next_press_is_not_flagged(self):
        run = self._chain("right_start", "right_stop", "right_start", "right_stop")
        self.assertEqual(run_pointer_conflicts(run, self._actions()), [])

    def test_repeat_body_is_walked_once(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="start", kind=RunNodeKind.ACTION, action_name="right_start"))
        run.add_node(RunNode(id="rep", kind=RunNodeKind.REPEAT, times=3))
        run.add_node(RunNode(id="jump", kind=RunNodeKind.ACTION, action_name="jump"))
        run.add_node(RunNode(id="stop", kind=RunNodeKind.ACTION, action_name="right_stop"))
        run.add_edge(RunEdge(id="e1", source="start", target="rep"))
        run.add_edge(RunEdge(id="e2", source="rep", target="jump", via="body"))
        run.add_edge(RunEdge(id="e3", source="rep", target="stop", via="after"))
        warnings = run_pointer_conflicts(run, self._actions())
        self.assertEqual(len(warnings), 1)
        self.assertIn("jump", warnings[0])

    def test_unknown_action_name_is_skipped_not_raised(self):
        run = self._chain("missing")
        self.assertEqual(run_pointer_conflicts(run, {}), [])

    def test_concurrent_fork_is_not_cross_checked(self):
        # a genuine fork -- both branches press pointer 0 independently; this is a real
        # potential race but run_pointer_conflicts deliberately doesn't reason about it (see
        # its own docstring), so it should NOT be flagged as a false positive either.
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="right_start"))
        run.add_node(RunNode(id="b", kind=RunNodeKind.ACTION, action_name="right_start"))
        run.add_node(RunNode(id="root", kind=RunNodeKind.DELAY, frames=1))
        run.add_edge(RunEdge(id="e1", source="root", target="a"))
        run.add_edge(RunEdge(id="e2", source="root", target="b"))
        self.assertEqual(run_pointer_conflicts(run, self._actions()), [])


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


class EventsLookAlikeTest(unittest.TestCase):
    def test_identical_events_look_alike(self):
        events = [PrimitiveEvent(kind=EventKind.TAP, x=10, y=20)]
        self.assertTrue(events_look_alike(events, events))

    def test_positions_within_tolerance_look_alike(self):
        a = [PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)]
        b = [PrimitiveEvent(kind=EventKind.TAP, x=115, y=90)]
        self.assertTrue(events_look_alike(a, b, position_tolerance_px=30))

    def test_positions_beyond_tolerance_dont_look_alike(self):
        a = [PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)]
        b = [PrimitiveEvent(kind=EventKind.TAP, x=500, y=500)]
        self.assertFalse(events_look_alike(a, b, position_tolerance_px=30))

    def test_wait_durations_are_ignored(self):
        a = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.WAIT, frames=5),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        b = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.WAIT, frames=200),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        self.assertTrue(events_look_alike(a, b))

    def test_different_kind_sequence_lengths_dont_look_alike(self):
        a = [PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)]
        b = [PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5), PrimitiveEvent(kind=EventKind.RELEASE)]
        self.assertFalse(events_look_alike(a, b))

    def test_key_events_compare_by_key_name_not_position(self):
        a = [PrimitiveEvent(kind=EventKind.KEY, key_name="back")]
        b = [PrimitiveEvent(kind=EventKind.KEY, key_name="back")]
        c = [PrimitiveEvent(kind=EventKind.KEY, key_name="home")]
        self.assertTrue(events_look_alike(a, b))
        self.assertFalse(events_look_alike(a, c))


class FindMatchingActionTest(unittest.TestCase):
    def test_finds_the_matching_action_name(self):
        actions = {
            "jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=900, y=800)]),
            "attack": Action(name="attack", events=[PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)]),
        }
        result = find_matching_action([PrimitiveEvent(kind=EventKind.TAP, x=905, y=795)], actions)
        self.assertEqual(result, "jump")

    def test_returns_none_when_nothing_matches(self):
        actions = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=900, y=800)])}
        result = find_matching_action([PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)], actions)
        self.assertIsNone(result)

    def test_picks_the_nearest_of_several_within_tolerance_candidates(self):
        actions = {
            "far": Action(name="far", events=[PrimitiveEvent(kind=EventKind.TAP, x=115, y=100)]),
            "near": Action(name="near", events=[PrimitiveEvent(kind=EventKind.TAP, x=103, y=101)]),
        }
        result = find_matching_action([PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)], actions,
                                       position_tolerance_px=30)
        self.assertEqual(result, "near")

    def test_on_ambiguous_called_with_every_qualifying_candidate_nearest_first(self):
        actions = {
            "far": Action(name="far", events=[PrimitiveEvent(kind=EventKind.TAP, x=115, y=100)]),
            "near": Action(name="near", events=[PrimitiveEvent(kind=EventKind.TAP, x=103, y=101)]),
        }
        seen = []
        find_matching_action([PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)], actions,
                              position_tolerance_px=30, on_ambiguous=seen.append)
        self.assertEqual(seen, [["near", "far"]])

    def test_on_ambiguous_not_called_when_only_one_candidate_qualifies(self):
        actions = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=900, y=800)])}
        seen = []
        find_matching_action([PrimitiveEvent(kind=EventKind.TAP, x=905, y=795)], actions,
                              on_ambiguous=seen.append)
        self.assertEqual(seen, [])


class ProjectRenameActionTest(unittest.TestCase):
    def test_rename_updates_the_actions_dict_and_the_actions_own_name(self):
        project = Project(name="game")
        project.add_action(Action(name="jump"))
        project.rename_action("jump", "jump_v2")
        self.assertNotIn("jump", project.actions)
        self.assertIn("jump_v2", project.actions)
        self.assertEqual(project.actions["jump_v2"].name, "jump_v2")

    def test_rename_cascades_to_hud_region_action_name_and_release_action_name(self):
        project = Project(name="game")
        project.add_action(Action(name="right_start"))
        project.add_action(Action(name="right_stop"))
        project.add_hud_region(HudRegion(name="right_button", action_name="right_start",
                                          release_action_name="right_stop"))
        updated = project.rename_action("right_start", "right_start_v2")
        self.assertEqual(project.hud_regions["right_button"].action_name, "right_start_v2")
        self.assertEqual(project.hud_regions["right_button"].release_action_name, "right_stop")
        self.assertEqual(updated, 1)

    def test_rename_cascades_to_hud_region_combo_action_name(self):
        project = Project(name="game")
        project.add_action(Action(name="right_jump"))
        project.add_hud_region_combo(HudRegionCombo(name="rj", region_names=["a", "b"], action_name="right_jump"))
        project.rename_action("right_jump", "run_and_jump")
        self.assertEqual(project.hud_region_combos["rj"].action_name, "run_and_jump")

    def test_rename_cascades_to_run_node_action_name(self):
        project = Project(name="game")
        project.add_action(Action(name="jump"))
        run = GameRun(name="main")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ACTION, action_name="jump"))
        run.add_node(RunNode(id="d", kind=RunNodeKind.DELAY, frames=5))
        project.add_run(run)
        project.rename_action("jump", "jump_v2")
        self.assertEqual(project.runs["main"].nodes["a"].action_name, "jump_v2")
        self.assertEqual(project.runs["main"].nodes["d"].frames, 5)

    def test_rename_to_same_name_is_a_no_op(self):
        project = Project(name="game")
        project.add_action(Action(name="jump"))
        self.assertEqual(project.rename_action("jump", "jump"), 0)

    def test_rename_missing_action_raises_key_error(self):
        project = Project(name="game")
        with self.assertRaises(KeyError):
            project.rename_action("missing", "new")

    def test_rename_to_an_existing_different_action_raises_value_error(self):
        project = Project(name="game")
        project.add_action(Action(name="jump"))
        project.add_action(Action(name="attack"))
        with self.assertRaises(ValueError):
            project.rename_action("jump", "attack")


class ProjectRenameHudRegionTest(unittest.TestCase):
    def test_rename_updates_the_hud_regions_dict_and_the_regions_own_name(self):
        project = Project(name="game")
        project.add_hud_region(HudRegion(name="right_button"))
        project.rename_hud_region("right_button", "right_button_v2")
        self.assertNotIn("right_button", project.hud_regions)
        self.assertEqual(project.hud_regions["right_button_v2"].name, "right_button_v2")

    def test_rename_cascades_to_combo_region_names(self):
        project = Project(name="game")
        project.add_hud_region(HudRegion(name="right_button"))
        project.add_hud_region(HudRegion(name="jump_button"))
        project.add_hud_region_combo(HudRegionCombo(name="rj", region_names=["right_button", "jump_button"],
                                                      action_name="right_jump"))
        updated = project.rename_hud_region("right_button", "run_button")
        self.assertEqual(set(project.hud_region_combos["rj"].region_names), {"run_button", "jump_button"})
        self.assertEqual(updated, 1)


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

    def test_action_match_tolerance_px_survives_to_dict_from_dict(self):
        project = Project(name="game", action_match_tolerance_px=45)
        restored = Project.from_dict(project.to_dict())
        self.assertEqual(restored.action_match_tolerance_px, 45)

    def test_action_match_tolerance_px_defaults_to_30_when_absent(self):
        restored = Project.from_dict({"name": "game"})
        self.assertEqual(restored.action_match_tolerance_px, 30)

    def test_time_scale_survives_to_dict_from_dict(self):
        project = Project(name="game", time_scale=1.5)
        restored = Project.from_dict(project.to_dict())
        self.assertEqual(restored.time_scale, 1.5)

    def test_time_scale_defaults_to_1_when_absent(self):
        restored = Project.from_dict({"name": "game"})
        self.assertEqual(restored.time_scale, 1.0)

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
        self.assertTrue(any("only valid from a repeat, compare, or find_template node" in w for w in warnings))

    def test_validate_flags_unknown_template_reference(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="missing"))
        warnings = run.validate(project_actions={}, project_templates={})
        self.assertTrue(any("unknown template" in w for w in warnings))

    def test_validate_compare_defaults_to_no_templates_known(self):
        # project_templates is optional -- omitting it should still flag any
        # COMPARE reference, same spirit as project_actions always being required.
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="hp_full"))
        warnings = run.validate(project_actions={})
        self.assertTrue(any("unknown template" in w for w in warnings))

    def test_validate_flags_compare_with_two_match_edges(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="hp_full"))
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="c", target="a", via="match"))
        run.add_edge(RunEdge(id="e2", source="c", target="b", via="match"))
        warnings = run.validate(project_actions={}, project_templates={"hp_full": object()})
        self.assertTrue(any("more than one match connection" in w for w in warnings))

    def test_clean_compare_graph_has_no_warnings(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="c", kind=RunNodeKind.COMPARE, template_name="hp_full"))
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="c", target="a", via="match"))
        run.add_edge(RunEdge(id="e2", source="c", target="b", via="no_match"))
        self.assertEqual(run.validate(project_actions={}, project_templates={"hp_full": object()}), [])

    def test_validate_flags_unknown_find_template_reference(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="f", kind=RunNodeKind.FIND_TEMPLATE, template_name="missing"))
        warnings = run.validate(project_actions={}, project_templates={})
        self.assertTrue(any("unknown template" in w for w in warnings))

    def test_validate_flags_find_template_with_two_found_edges(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="f", kind=RunNodeKind.FIND_TEMPLATE, template_name="coin"))
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="f", target="a", via="found"))
        run.add_edge(RunEdge(id="e2", source="f", target="b", via="found"))
        warnings = run.validate(project_actions={}, project_templates={"coin": object()})
        self.assertTrue(any("more than one found connection" in w for w in warnings))

    def test_clean_find_template_graph_has_no_warnings(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="f", kind=RunNodeKind.FIND_TEMPLATE, template_name="coin"))
        run.add_node(RunNode(id="a", kind=RunNodeKind.DELAY))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="f", target="a", via="found"))
        run.add_edge(RunEdge(id="e2", source="f", target="b", via="not_found"))
        self.assertEqual(run.validate(project_actions={}, project_templates={"coin": object()}), [])

    def test_validate_flags_unknown_assert_template_reference(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ASSERT, template_name="missing", label="cleared_gap"))
        warnings = run.validate(project_actions={}, project_templates={})
        self.assertTrue(any("unknown template" in w for w in warnings))

    def test_validate_flags_assert_with_no_label(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ASSERT, template_name="hp_full"))
        warnings = run.validate(project_actions={}, project_templates={"hp_full": object()})
        self.assertTrue(any("no label" in w for w in warnings))

    def test_validate_flags_assert_with_via_edge(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ASSERT, template_name="hp_full", label="hp_ok"))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="a", target="b", via="match"))
        warnings = run.validate(project_actions={}, project_templates={"hp_full": object()})
        self.assertTrue(any("only valid from a repeat, compare, or find_template node" in w for w in warnings))

    def test_clean_assert_graph_has_no_warnings(self):
        run = GameRun(name="r")
        run.add_node(RunNode(id="a", kind=RunNodeKind.ASSERT, template_name="hp_full", label="hp_ok"))
        run.add_node(RunNode(id="b", kind=RunNodeKind.DELAY))
        run.add_edge(RunEdge(id="e1", source="a", target="b"))
        self.assertEqual(run.validate(project_actions={}, project_templates={"hp_full": object()}), [])

    def test_assert_round_trips_label_and_template(self):
        node = RunNode(id="a", kind=RunNodeKind.ASSERT, template_name="hp_full", label="hp_ok")
        restored = RunNode.from_dict(node.to_dict())
        self.assertEqual((restored.template_name, restored.label), ("hp_full", "hp_ok"))

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


class ImageTemplateRoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_fields(self):
        template = ImageTemplate(name="hp_full", x=10, y=20, width=100, height=30,
                                  threshold=0.85, image_w=100, image_h=30, pixels_b64="AAAA")
        restored = ImageTemplate.from_dict(template.to_dict())
        self.assertEqual(restored.name, "hp_full")
        self.assertEqual((restored.x, restored.y, restored.width, restored.height), (10, 20, 100, 30))
        self.assertEqual(restored.threshold, 0.85)
        self.assertEqual(restored.pixels_b64, "AAAA")

    def test_project_templates_survive_to_dict_from_dict(self):
        project = Project(name="game")
        project.add_template(ImageTemplate(name="hp_full", x=1, y=2, width=3, height=4))
        restored = Project.from_dict(project.to_dict())
        self.assertIn("hp_full", restored.templates)
        self.assertEqual(restored.templates["hp_full"].width, 3)


class HudRegionTest(unittest.TestCase):
    def test_round_trip_preserves_fields(self):
        region = HudRegion(name="jump_button", x=900, y=1800, width=150, height=150, action_name="jump")
        restored = HudRegion.from_dict(region.to_dict())
        self.assertEqual(restored.name, "jump_button")
        self.assertEqual((restored.x, restored.y, restored.width, restored.height), (900, 1800, 150, 150))
        self.assertEqual(restored.action_name, "jump")

    def test_project_hud_regions_survive_to_dict_from_dict(self):
        project = Project(name="game")
        project.add_hud_region(HudRegion(name="jump_button", x=1, y=2, width=3, height=4, action_name="jump"))
        restored = Project.from_dict(project.to_dict())
        self.assertIn("jump_button", restored.hud_regions)
        self.assertEqual(restored.hud_regions["jump_button"].action_name, "jump")

    def test_contains_is_half_open_on_far_edges(self):
        region = HudRegion(name="r", x=0, y=0, width=10, height=10)
        self.assertTrue(region.contains(0, 0))
        self.assertTrue(region.contains(9, 9))
        self.assertFalse(region.contains(10, 10))
        self.assertFalse(region.contains(-1, 5))

    def test_area(self):
        self.assertEqual(HudRegion(name="r", width=10, height=20).area, 200)

    def test_is_hold_reflects_release_action_name(self):
        self.assertFalse(HudRegion(name="jump_button", action_name="jump").is_hold)
        self.assertTrue(HudRegion(name="right_button", action_name="right_start",
                                   release_action_name="right_stop").is_hold)

    def test_round_trip_preserves_release_action_name(self):
        region = HudRegion(name="right_button", action_name="right_start", release_action_name="right_stop")
        restored = HudRegion.from_dict(region.to_dict())
        self.assertEqual(restored.release_action_name, "right_stop")
        self.assertTrue(restored.is_hold)


class HudRegionComboTest(unittest.TestCase):
    def test_round_trip_preserves_fields(self):
        combo = HudRegionCombo(name="right_jump", region_names=["right_button", "jump_button"],
                                action_name="right_jump")
        restored = HudRegionCombo.from_dict(combo.to_dict())
        self.assertEqual(restored.name, "right_jump")
        self.assertEqual(set(restored.region_names), {"right_button", "jump_button"})
        self.assertEqual(restored.action_name, "right_jump")

    def test_project_hud_region_combos_survive_to_dict_from_dict(self):
        project = Project(name="game")
        project.add_hud_region_combo(HudRegionCombo(name="right_jump", region_names=["a", "b"], action_name="rj"))
        restored = Project.from_dict(project.to_dict())
        self.assertIn("right_jump", restored.hud_region_combos)
        self.assertEqual(restored.hud_region_combos["right_jump"].action_name, "rj")


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class ImageTemplateCaptureCompareTest(unittest.TestCase):
    def test_capture_then_compare_identical_frame_is_a_perfect_match(self):
        # a 100x50 frame, reference resolution equal to frame size for simplicity;
        # a mid-gray rectangle at (10, 10)-(40, 30) is the "hp bar" being captured.
        frame = np.zeros((50, 100), dtype=np.uint8)
        frame[10:30, 10:40] = 200
        template = ImageTemplate.capture(
            "hp_full", x=10, y=10, width=30, height=20,
            frame_w=100, frame_h=50, frame=frame, ref_res_w=100, ref_res_h=50)
        self.assertEqual((template.image_w, template.image_h), (30, 20))
        similarity = template.similarity(frame_w=100, frame_h=50, frame=frame, ref_w=100, ref_h=50)
        self.assertAlmostEqual(similarity, 1.0, places=6)
        self.assertTrue(template.matches(frame_w=100, frame_h=50, frame=frame, ref_w=100, ref_h=50))

    def test_compare_against_a_different_region_is_not_a_match(self):
        frame = np.zeros((50, 100), dtype=np.uint8)
        frame[10:30, 10:40] = 200
        template = ImageTemplate.capture(
            "hp_full", x=10, y=10, width=30, height=20,
            frame_w=100, frame_h=50, frame=frame, ref_res_w=100, ref_res_h=50)

        empty_frame = np.zeros((50, 100), dtype=np.uint8)
        similarity = template.similarity(frame_w=100, frame_h=50, frame=empty_frame, ref_w=100, ref_h=50)
        self.assertLess(similarity, 0.9)
        self.assertFalse(template.matches(frame_w=100, frame_h=50, frame=empty_frame, ref_w=100, ref_h=50))

    def test_compare_scales_region_to_a_differently_sized_live_frame(self):
        # captured at 100x50, compared against a 200x100 frame (e.g. a less-downscaled
        # mirror on a later connection) -- the region must still be found by ratio.
        frame = np.zeros((50, 100), dtype=np.uint8)
        frame[10:30, 10:40] = 200
        template = ImageTemplate.capture(
            "hp_full", x=10, y=10, width=30, height=20,
            frame_w=100, frame_h=50, frame=frame, ref_res_w=100, ref_res_h=50)

        bigger_frame = np.zeros((100, 200), dtype=np.uint8)
        bigger_frame[20:60, 20:80] = 200   # same region, doubled
        similarity = template.similarity(frame_w=200, frame_h=100, frame=bigger_frame, ref_w=100, ref_h=50)
        self.assertGreater(similarity, 0.95)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class ImageTemplateFindTest(unittest.TestCase):
    def test_find_locates_template_moved_elsewhere_in_the_frame(self):
        # captured at (10, 10)-(40, 30); the live frame has since moved the same
        # patch down and to the right, to (60, 25)-(90, 45) -- find() must not
        # just re-check the original (x, y), it must search for the new spot.
        capture_frame = np.zeros((50, 100), dtype=np.uint8)
        capture_frame[10:30, 10:40] = 200
        template = ImageTemplate.capture(
            "coin", x=10, y=10, width=30, height=20,
            frame_w=100, frame_h=50, frame=capture_frame, ref_res_w=100, ref_res_h=50)

        moved_frame = np.zeros((50, 100), dtype=np.uint8)
        moved_frame[25:45, 60:90] = 200
        result = template.find(frame_w=100, frame_h=50, frame=moved_frame, ref_w=100, ref_h=50, stride=2)
        self.assertIsNotNone(result)
        x, y, similarity = result
        self.assertAlmostEqual(x, 60, delta=2)
        self.assertAlmostEqual(y, 25, delta=2)
        self.assertGreater(similarity, 0.95)

    def test_find_returns_none_for_an_uncaptured_template(self):
        template = ImageTemplate(name="coin", x=0, y=0, width=10, height=10)
        frame = np.zeros((50, 100), dtype=np.uint8)
        self.assertIsNone(template.find(frame_w=100, frame_h=50, frame=frame, ref_w=100, ref_h=50))

    def test_find_returns_none_when_template_region_is_bigger_than_the_frame(self):
        # width=150 in a reference resolution equal to the frame size (100x50, so
        # ImageTemplate's ref->frame scaling is identity) means the region can
        # never fit -- e.g. a template captured before a reference-resolution
        # change that shrank the frame.
        template = ImageTemplate(name="coin", x=0, y=0, width=150, height=80,
                                  image_w=1, image_h=1, pixels_b64=base64.b64encode(b"\x00").decode("ascii"))
        frame = np.zeros((50, 100), dtype=np.uint8)
        self.assertIsNone(template.find(frame_w=100, frame_h=50, frame=frame, ref_w=100, ref_h=50))


if __name__ == "__main__":
    unittest.main()
