"""export_action_map tests -- pure model/dict assertions, no device."""
import unittest

from ..gym_export import export_action_map
from ..model import Action, ActionKind, EventKind, HudRegion, PrimitiveEvent, Project


def _mario_project() -> Project:
    project = Project(name="mario", reference_width=2670, reference_height=1200)
    project.add_action(Action(name="left_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=265, y=1072)]))
    project.add_action(Action(name="left_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)]))
    project.add_action(Action(name="right_start", events=[PrimitiveEvent(kind=EventKind.PRESS, x=742, y=1063)]))
    project.add_action(Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE)]))
    project.add_action(Action(name="jump", events=[
        PrimitiveEvent(kind=EventKind.PRESS, x=2396, y=1070, pointer_id=1),
        PrimitiveEvent(kind=EventKind.WAIT, frames=10, pointer_id=1),
        PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
    ]))
    project.add_action(Action(name="attack", events=[
        PrimitiveEvent(kind=EventKind.PRESS, x=1952, y=1060, pointer_id=1),
        PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
    ]))
    project.add_action(Action(name="right_jump", events=[
        PrimitiveEvent(kind=EventKind.PRESS, x=640, y=1045, pointer_id=0),
        PrimitiveEvent(kind=EventKind.WAIT, frames=1),
        PrimitiveEvent(kind=EventKind.PRESS, x=2447, y=1080, pointer_id=1),
        PrimitiveEvent(kind=EventKind.WAIT, frames=5, pointer_id=1),
        PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
    ]))
    project.add_hud_region(HudRegion(name="left_button", x=117, y=950, width=253, height=203,
                                      action_name="left_start", release_action_name="left_stop"))
    project.add_hud_region(HudRegion(name="right_button", x=534, y=947, width=267, height=203,
                                      action_name="right_start", release_action_name="right_stop"))
    project.add_hud_region(HudRegion(name="jump_button", x=2270, y=960, width=270, height=210,
                                      action_name="jump"))
    project.add_hud_region(HudRegion(name="fire_button", x=1856, y=967, width=233, height=190,
                                      action_name="attack"))
    return project


class ExportButtonsTest(unittest.TestCase):
    def test_hold_region_exports_tap_and_hold_press_modes(self):
        result = export_action_map(_mario_project())
        self.assertEqual(result["buttons"]["right_button"]["press_modes"], ["tap", "hold"])

    def test_hold_region_uses_its_start_actions_pointer_id(self):
        result = export_action_map(_mario_project())
        self.assertEqual(result["buttons"]["right_button"]["pointer_id"], 0)

    def test_plain_region_exports_tap_only(self):
        result = export_action_map(_mario_project())
        self.assertEqual(result["buttons"]["jump_button"]["press_modes"], ["tap"])
        self.assertEqual(result["buttons"]["jump_button"]["pointer_id"], 1)

    def test_region_rectangle_becomes_its_inscribed_circle(self):
        result = export_action_map(_mario_project())
        region = result["buttons"]["jump_button"]["region"]
        self.assertEqual(region, {"cx": 2270 + 135, "cy": 960 + 105, "radius": 105})

    def test_top_level_shape_matches_the_plan_schema(self):
        result = export_action_map(_mario_project())
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["tier"], "button")
        self.assertEqual(result["reference_resolution"], {"width": 2670, "height": 1200})

    def test_missing_action_for_a_region_is_skipped_and_logged(self):
        project = Project(name="p")
        project.add_hud_region(HudRegion(name="ghost_button", action_name="missing"))
        logs = []
        result = export_action_map(project, on_log=logs.append)
        self.assertEqual(result["buttons"], {})
        self.assertTrue(any("not found" in line for line in logs))


class ExportMacrosTest(unittest.TestCase):
    def test_compound_multi_pointer_macro_goes_to_compound_macros(self):
        result = export_action_map(_mario_project())
        self.assertIn("right_jump", result["compound_macros"])
        self.assertNotIn("right_jump", result["macros"])
        events = result["compound_macros"]["right_jump"]["events"]
        self.assertEqual(len(events), 6)

    def test_single_button_hold_macro_goes_to_macros(self):
        # structurally this looks just like a plain single-button hold gesture (indistinguishable
        # from e.g. "jump" itself), so infer_kind() alone won't call it a macro -- matching
        # docs/opengym_implementation_plan.md §7.4's "opt-in per button" framing, a human tags
        # it explicitly (an integrator who knows this specific duration matters).
        project = _mario_project()
        project.add_action(Action(name="long_jump", kind=ActionKind.MACRO, events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=2396, y=1070, pointer_id=1),
            PrimitiveEvent(kind=EventKind.WAIT, frames=20, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
        ]))
        result = export_action_map(project)
        self.assertEqual(result["macros"]["long_jump"],
                          {"button": "jump_button", "mode": "hold", "hold_duration_frames": 20})
        self.assertNotIn("long_jump", result.get("compound_macros", {}))

    def test_momentary_actions_used_by_a_button_are_not_listed_as_unbuttoned(self):
        logs = []
        export_action_map(_mario_project(), on_log=logs.append)
        self.assertFalse(any("jump" in line and "not part of" in line for line in logs))

    def test_action_with_no_region_and_not_a_macro_is_reported_as_unbuttoned(self):
        project = _mario_project()
        project.add_action(Action(name="secret_tap", events=[PrimitiveEvent(kind=EventKind.TAP, x=1, y=1)]))
        logs = []
        export_action_map(project, on_log=logs.append)
        self.assertTrue(any("secret_tap" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
