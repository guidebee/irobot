"""Pure model tests -- no Qt, no socket, no device. Run with:
    python -m unittest discover -s irobot_gym_ide/tests
(or via pytest, which auto-discovers unittest.TestCase classes too)."""
import base64
import unittest

from ..model import (
    Action, EventKind, GameRun, HudRegion, HudRegionCombo, ImageTemplate, PrimitiveEvent, Project, RunEdge, RunNode,
    RunNodeKind, conflicting_pointer_actions, orphan_releases,
)

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


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
