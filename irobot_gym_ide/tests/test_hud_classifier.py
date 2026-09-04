"""classify_session tests -- pure model, no Qt/socket/device."""
import unittest

from ..hud_classifier import classify_session
from ..model import EventKind, GameplaySession, HudRegion, PrimitiveEvent


def _regions(*regions) -> dict:
    return {r.name: r for r in regions}


class TapClassificationTest(unittest.TestCase):
    def test_tap_inside_region_is_classified(self):
        session = GameplaySession(name="s", events=[
            PrimitiveEvent(kind=EventKind.TAP, x=905, y=1805),
        ])
        regions = _regions(HudRegion(name="jump_button", x=900, y=1800, width=100, height=100, action_name="jump"))
        segments = classify_session(session, regions)
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        self.assertEqual((seg.start_index, seg.end_index, seg.action_name, seg.label), (0, 1, "jump", "jump_button"))

    def test_tap_outside_every_region_is_unclassified(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(HudRegion(name="jump_button", x=900, y=1800, width=100, height=100, action_name="jump"))
        self.assertEqual(classify_session(session, regions), [])

    def test_no_regions_classifies_nothing(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        self.assertEqual(classify_session(session, {}), [])


class PressReleaseClassificationTest(unittest.TestCase):
    def test_classifies_by_the_press_points_region_not_the_release(self):
        # a drag that starts inside "left_button" and ends somewhere else --
        # classification should follow where the finger landed, not where it lifted.
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=110, y=110, pointer_id=0),
            PrimitiveEvent(kind=EventKind.MOVE, x=500, y=500, pointer_id=0),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        regions = _regions(HudRegion(name="left_button", x=100, y=100, width=50, height=50, action_name="move_left"))
        segments = classify_session(session, regions)
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0].start_index, segments[0].end_index), (0, 3))
        self.assertEqual(segments[0].action_name, "move_left")

    def test_release_with_no_open_press_is_skipped_and_logged(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0)])
        logs = []
        segments = classify_session(session, {}, on_log=logs.append)
        self.assertEqual(segments, [])
        self.assertTrue(any("no open PRESS" in line for line in logs))


class OverlappingRegionsTest(unittest.TestCase):
    def test_smaller_region_wins_when_regions_overlap(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=50, y=50)])
        regions = _regions(
            HudRegion(name="big_attack_area", x=0, y=0, width=200, height=200, action_name="attack"),
            HudRegion(name="special_hotspot", x=40, y=40, width=20, height=20, action_name="special_move"),
        )
        segments = classify_session(session, regions)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].action_name, "special_move")


class MultipleGesturesTest(unittest.TestCase):
    def test_taps_and_hold_release_all_classified_in_order(self):
        events = [
            PrimitiveEvent(kind=EventKind.TAP, x=5, y=5),                     # -> jump
            PrimitiveEvent(kind=EventKind.WAIT, frames=3),
            PrimitiveEvent(kind=EventKind.PRESS, x=105, y=5, pointer_id=1),   # -> hold_left ...
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),             # ... ends here
            PrimitiveEvent(kind=EventKind.TAP, x=999, y=999),                 # unclassified
        ]
        session = GameplaySession(name="s", events=events)
        regions = _regions(
            HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump"),
            HudRegion(name="left_button", x=100, y=0, width=10, height=10, action_name="hold_left"),
        )
        segments = classify_session(session, regions)
        self.assertEqual([s.action_name for s in segments], ["jump", "hold_left"])
        self.assertEqual([(s.start_index, s.end_index) for s in segments], [(0, 1), (2, 4)])


if __name__ == "__main__":
    unittest.main()
