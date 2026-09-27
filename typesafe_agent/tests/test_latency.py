import unittest

from typesafe_agent.latency import measure_action_latency


class FakeConnection:
    """Enough of LiveConnection's surface for measure_action_latency: a
    scripted sequence of latest_thumbnail() results and a recording
    run_action() that never touches a real socket."""

    def __init__(self, thumbnails):
        self._thumbnails = list(thumbnails)
        self.ran_actions = []

    def latest_thumbnail(self):
        if not self._thumbnails:
            return None
        return self._thumbnails.pop(0) if len(self._thumbnails) > 1 else self._thumbnails[0]

    def run_action(self, action, ref_w, ref_h):
        self.ran_actions.append((action, ref_w, ref_h))
        return []


class MeasureActionLatencyTests(unittest.TestCase):
    def test_reports_time_to_phash_change(self):
        # First call (baseline, before settle_s sleep) sees phash b"a"; every
        # call afterwards sees b"b" once popped down to the last entry.
        connection = FakeConnection([(1, 1, b"\x00", b"a"), (1, 1, b"\x00", b"b")])
        sample = measure_action_latency(
            connection, action="jump-action", ref_w=100, ref_h=200, timeout_s=1.0, settle_s=0.0
        )
        self.assertFalse(sample.timed_out)
        self.assertGreaterEqual(sample.round_trip_ms, 0.0)
        self.assertEqual(connection.ran_actions, [("jump-action", 100, 200)])

    def test_times_out_when_phash_never_changes(self):
        connection = FakeConnection([(1, 1, b"\x00", b"a")])
        sample = measure_action_latency(
            connection, action="jump-action", ref_w=100, ref_h=200, timeout_s=0.05, settle_s=0.0
        )
        self.assertTrue(sample.timed_out)
        self.assertEqual(sample.round_trip_ms, 50.0)


if __name__ == "__main__":
    unittest.main()
