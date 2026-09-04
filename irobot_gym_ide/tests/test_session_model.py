"""GameplaySession/SessionSegment tests -- pure model, no Qt/socket/device."""
import unittest

from ..model import Action, EventKind, GameplaySession, PrimitiveEvent, SessionSegment


def _events(n: int) -> list:
    return [PrimitiveEvent(kind=EventKind.TAP, x=i, y=i) for i in range(n)]


class RoundTripTest(unittest.TestCase):
    def test_round_trip_preserves_events_and_segments(self):
        session = GameplaySession(
            name="playthrough_1", created_at="2026-09-04T00:00:00", source="device",
            reference_width=1080, reference_height=2400,
            events=_events(5),
            segments=[SessionSegment(start_index=0, end_index=2, action_name="jump", label="hop over gap")],
            notes="first attempt",
        )
        restored = GameplaySession.from_dict(session.to_dict())
        self.assertEqual(restored.name, "playthrough_1")
        self.assertEqual(restored.source, "device")
        self.assertEqual((restored.reference_width, restored.reference_height), (1080, 2400))
        self.assertEqual(len(restored.events), 5)
        self.assertEqual(restored.events[3].x, 3)
        self.assertEqual(len(restored.segments), 1)
        seg = restored.segments[0]
        self.assertEqual((seg.start_index, seg.end_index, seg.action_name, seg.label), (0, 2, "jump", "hop over gap"))
        self.assertEqual(restored.notes, "first attempt")

    def test_defaults_round_trip_with_no_segments(self):
        session = GameplaySession(name="empty", events=_events(2))
        restored = GameplaySession.from_dict(session.to_dict())
        self.assertEqual(restored.segments, [])


class ValidateTest(unittest.TestCase):
    def test_clean_session_has_no_warnings(self):
        session = GameplaySession(name="s", events=_events(6), segments=[
            SessionSegment(start_index=0, end_index=3, action_name="a"),
            SessionSegment(start_index=3, end_index=6, action_name="b"),
        ])
        self.assertEqual(session.validate({"a": Action(name="a"), "b": Action(name="b")}), [])

    def test_out_of_range_segment_warns(self):
        session = GameplaySession(name="s", events=_events(3), segments=[
            SessionSegment(start_index=0, end_index=10, action_name="a"),
        ])
        warnings = session.validate({"a": Action(name="a")})
        self.assertTrue(any("invalid range" in w for w in warnings))

    def test_inverted_segment_warns(self):
        session = GameplaySession(name="s", events=_events(3), segments=[
            SessionSegment(start_index=2, end_index=1, action_name="a"),
        ])
        warnings = session.validate({"a": Action(name="a")})
        self.assertTrue(any("invalid range" in w for w in warnings))

    def test_overlapping_segments_warn(self):
        session = GameplaySession(name="s", events=_events(6), segments=[
            SessionSegment(start_index=0, end_index=4, action_name="a"),
            SessionSegment(start_index=2, end_index=6, action_name="a"),
        ])
        warnings = session.validate({"a": Action(name="a")})
        self.assertTrue(any("overlaps" in w for w in warnings))

    def test_unknown_action_name_warns(self):
        session = GameplaySession(name="s", events=_events(3), segments=[
            SessionSegment(start_index=0, end_index=2, action_name="ghost"),
        ])
        warnings = session.validate({})
        self.assertTrue(any("unknown action" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
