"""LiveConnection.send_primitive tests -- no real socket: `_control_sock`/`_video_sock`
are faked non-None to satisfy `connected`, and `_send_control` is patched to capture the
wire messages it would have sent instead of actually writing to a socket. Same
no-real-device spirit as test_run_engine.py/test_session_replay.py's fake connections, just
exercising the real LiveConnection class itself since the resolution-rescale/time_scale
logic under test lives there, not in a substitutable fake."""
import unittest
from unittest.mock import patch

from ..connection import FRAME_MS, LiveConnection
from ..model import EventKind, PrimitiveEvent


def _make_connected(host="host", port=1):
    conn = LiveConnection(host, port)
    conn._control_sock = object()
    conn._video_sock = object()
    return conn


class ResolutionRescaleTest(unittest.TestCase):
    def test_no_detected_resolution_sends_ref_size_and_position_unscaled(self):
        conn = _make_connected()
        sent = []
        with patch.object(conn, "_send_control", side_effect=lambda msg: sent.append(msg)):
            conn.send_primitive(PrimitiveEvent(kind=EventKind.PRESS, x=100, y=200), ref_w=1000, ref_h=2000)
        point = sent[0]["touch_event"]["position"]["point"]
        size = sent[0]["touch_event"]["position"]["screen_size"]
        self.assertEqual((point["x"], point["y"]), (100, 200))
        self.assertEqual((size["width"], size["height"]), (1000, 2000))

    def test_detected_resolution_matching_reference_is_unchanged(self):
        conn = _make_connected()
        conn._latest_resolution = (1000, 2000)
        sent = []
        with patch.object(conn, "_send_control", side_effect=lambda msg: sent.append(msg)):
            conn.send_primitive(PrimitiveEvent(kind=EventKind.PRESS, x=100, y=200), ref_w=1000, ref_h=2000)
        point = sent[0]["touch_event"]["position"]["point"]
        self.assertEqual((point["x"], point["y"]), (100, 200))

    def test_detected_resolution_differing_from_reference_rescales_position_and_screen_size(self):
        # a project authored at 1000x2000 opened against a device that actually negotiated
        # 500x1000 -- the recorded (100, 200) should land at the proportionally same spot,
        # (50, 100), and screen_size sent to the device must be its own real resolution
        # (irobot_server drops anything else, see agent_client.touch_message's docstring).
        conn = _make_connected()
        conn._latest_resolution = (500, 1000)
        sent = []
        with patch.object(conn, "_send_control", side_effect=lambda msg: sent.append(msg)):
            conn.send_primitive(PrimitiveEvent(kind=EventKind.PRESS, x=100, y=200), ref_w=1000, ref_h=2000)
        point = sent[0]["touch_event"]["position"]["point"]
        size = sent[0]["touch_event"]["position"]["screen_size"]
        self.assertEqual((point["x"], point["y"]), (50, 100))
        self.assertEqual((size["width"], size["height"]), (500, 1000))

    def test_release_with_no_position_is_not_rescaled(self):
        conn = _make_connected()
        conn._latest_resolution = (500, 1000)
        conn._held_pointers.add(0)
        sent = []
        with patch.object(conn, "_send_control", side_effect=lambda msg: sent.append(msg)):
            conn.send_primitive(PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0), ref_w=1000, ref_h=2000)
        point = sent[0]["touch_event"]["position"]["point"]
        self.assertEqual((point["x"], point["y"]), (0, 0))

    def test_tap_rescales_both_down_and_up_messages(self):
        conn = _make_connected()
        conn._latest_resolution = (500, 1000)
        sent = []
        with patch.object(conn, "_send_control", side_effect=lambda msg: sent.append(msg)):
            conn.send_primitive(PrimitiveEvent(kind=EventKind.TAP, x=100, y=200), ref_w=1000, ref_h=2000)
        self.assertEqual(len(sent), 2)
        for msg in sent:
            point = msg["touch_event"]["position"]["point"]
            self.assertEqual((point["x"], point["y"]), (50, 100))


class TimeScaleTest(unittest.TestCase):
    def test_default_time_scale_leaves_wait_duration_unchanged(self):
        conn = _make_connected()
        with patch("irobot_gym_ide.connection.time.sleep") as sleep_mock:
            conn.send_primitive(PrimitiveEvent(kind=EventKind.WAIT, frames=10), ref_w=100, ref_h=100)
        sleep_mock.assert_called_once_with(10 * FRAME_MS / 1000.0)

    def test_time_scale_multiplies_wait_duration(self):
        conn = _make_connected()
        conn.time_scale = 1.5
        with patch("irobot_gym_ide.connection.time.sleep") as sleep_mock:
            conn.send_primitive(PrimitiveEvent(kind=EventKind.WAIT, frames=10), ref_w=100, ref_h=100)
        sleep_mock.assert_called_once_with(10 * FRAME_MS * 1.5 / 1000.0)


if __name__ == "__main__":
    unittest.main()
