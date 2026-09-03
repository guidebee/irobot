"""Pure parser tests -- no adb, no device, no threading. The getevent/-pl/
dumpsys fixtures below are verbatim excerpts captured from a real device
during development (see docs/irobot_gym_ide_design.md §11), not hand-invented,
so these tests pin the parser against the actual wire format a real Android
touch controller (and a real rotation bug) produced."""
import unittest

from ..device_recorder import (
    RecordedTouch, apply_rotation, gesture_to_events, merge_gestures_into_events,
    parse_axis_ranges, parse_getevent_stream, parse_touch_rotation, segment_into_gestures,
)
from ..model import EventKind

# Verbatim excerpt: device headers (getevent -lt prints these before
# streaming) followed by one real single-finger tap-and-drag, captured live
# from a Samsung device's "synaptics_tcm_touch" panel. Trimmed to the
# down -> a couple of moves -> up transitions that matter for the test.
_REAL_GETEVENT_EXCERPT = """\
add device 1: /dev/input/event4
  name:     "ff_key"
add device 2: /dev/input/event3
  name:     "mt6878-mt6369 Headset Jack"
add device 3: /dev/input/event2
  name:     "synaptics_tcm_touch"
add device 4: /dev/input/event0
  name:     "gpio-keys"
add device 5: /dev/input/event1
  name:     "mtk-pmic-keys"
[  582809.526611] /dev/input/event0: EV_KEY       KEY_VOLUMEDOWN       DOWN
[  582809.526611] /dev/input/event0: EV_SYN       SYN_REPORT           00000000
[  582809.526611] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID   00007c75
[  582809.526611] /dev/input/event2: EV_KEY       BTN_TOUCH            DOWN
[  582809.526611] /dev/input/event2: EV_KEY       BTN_TOOL_FINGER      DOWN
[  582809.526611] /dev/input/event2: EV_ABS       ABS_MT_POSITION_X    000002a5
[  582809.526611] /dev/input/event2: EV_ABS       ABS_MT_POSITION_Y    000003fd
[  582809.526611] /dev/input/event2: EV_ABS       ABS_MT_TOUCH_MINOR   0000000a
[  582809.526611] /dev/input/event2: EV_SYN       SYN_REPORT           00000000
[  582809.727895] /dev/input/event2: EV_ABS       ABS_MT_POSITION_X    000002ef
[  582809.727895] /dev/input/event2: EV_ABS       ABS_MT_POSITION_Y    0000019d
[  582809.727895] /dev/input/event2: EV_ABS       ABS_MT_TOUCH_MINOR   0000000c
[  582809.727895] /dev/input/event2: EV_SYN       SYN_REPORT           00000000
[  582809.735993] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID   ffffffff
[  582809.735993] /dev/input/event2: EV_KEY       BTN_TOUCH            UP
[  582809.735993] /dev/input/event2: EV_KEY       BTN_TOOL_FINGER      UP
[  582809.735993] /dev/input/event2: EV_SYN       SYN_REPORT           00000000
"""

# Verbatim excerpt of `adb shell getevent -pl` output, real device, trimmed
# to the touchscreen block plus one distractor block (a plain button device
# with no ABS_MT axes at all, to confirm it's correctly skipped).
_REAL_PL_EXCERPT = """\
add device 3: /dev/input/event2
  name:     "synaptics_tcm_touch"
  events:
    KEY (0001): BTN_TOOL_FINGER       BTN_TOUCH
    ABS (0003): ABS_X                 : value 0, min 0, max 1199, fuzz 0, flat 0, resolution 0
                ABS_Y                 : value 0, min 0, max 2669, fuzz 0, flat 0, resolution 0
                ABS_MT_SLOT           : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                ABS_MT_TOUCH_MAJOR    : value 0, min 0, max 255, fuzz 0, flat 0, resolution 0
                ABS_MT_TOUCH_MINOR    : value 0, min 0, max 255, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X     : value 0, min 0, max 1199, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 2669, fuzz 0, flat 0, resolution 0
                ABS_MT_TRACKING_ID    : value 0, min 0, max 65535, fuzz 0, flat 0, resolution 0
  input props:
    INPUT_PROP_DIRECT
add device 4: /dev/input/event0
  name:     "gpio-keys"
  events:
    KEY (0001): KEY_VOLUMEDOWN
  input props:
    <none>
"""

# Verbatim excerpt of `adb shell dumpsys input` output, real device, trimmed
# to the "Viewport INTERNAL" line that carries the currently-applied display
# rotation -- orientation=1 here is Surface.ROTATION_90, matching a landscape
# game running on this device's portrait-native touch panel.
_REAL_DUMPSYS_INPUT_EXCERPT = """\
      Viewport INTERNAL: displayId=0, uniqueId=local:4627039422300187648, port=0, orientation=1, logicalFrame=[0, 0, 2670, 1200], physicalFrame=[0, 0, 2670, 1200], deviceSize=[2670, 1200], isActive=[1]
"""


class ParseGeteventStreamTest(unittest.TestCase):
    def test_auto_detects_touchscreen_and_ignores_other_devices(self):
        touches = parse_getevent_stream(_REAL_GETEVENT_EXCERPT.splitlines())
        # the KEY_VOLUMEDOWN line on event0 must not produce a touch, and
        # must not be mistaken for the touchscreen
        self.assertTrue(all(isinstance(t, RecordedTouch) for t in touches))
        kinds = [t.kind for t in touches]
        self.assertEqual(kinds, ["down", "move", "up"])

    def test_down_and_up_positions_match_the_real_capture(self):
        touches = parse_getevent_stream(_REAL_GETEVENT_EXCERPT.splitlines())
        down, move, up = touches
        self.assertEqual((down.x, down.y), (0x2A5, 0x3FD))
        self.assertEqual((move.x, move.y), (0x2EF, 0x19D))
        # "up" carries the last known position, not a fresh one (getevent
        # doesn't repeat POSITION_X/Y on the release frame)
        self.assertEqual((up.x, up.y), (0x2EF, 0x19D))

    def test_relative_timestamps_start_at_zero(self):
        touches = parse_getevent_stream(_REAL_GETEVENT_EXCERPT.splitlines())
        self.assertAlmostEqual(touches[0].t, 0.0, places=6)
        self.assertGreater(touches[-1].t, 0.0)

    def test_two_concurrent_fingers_stay_demuxed_by_slot(self):
        lines = [
            'add device 1: /dev/input/event2',
            '  name:     "synaptics_tcm_touch"',
            '[  100.000000] /dev/input/event2: EV_ABS       ABS_MT_SLOT           00000000',
            '[  100.000000] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID    00000001',
            '[  100.000000] /dev/input/event2: EV_ABS       ABS_MT_POSITION_X     00000064',
            '[  100.000000] /dev/input/event2: EV_ABS       ABS_MT_POSITION_Y     00000064',
            '[  100.000000] /dev/input/event2: EV_SYN       SYN_REPORT            00000000',
            '[  100.010000] /dev/input/event2: EV_ABS       ABS_MT_SLOT           00000001',
            '[  100.010000] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID    00000002',
            '[  100.010000] /dev/input/event2: EV_ABS       ABS_MT_POSITION_X     000000c8',
            '[  100.010000] /dev/input/event2: EV_ABS       ABS_MT_POSITION_Y     000000c8',
            '[  100.010000] /dev/input/event2: EV_SYN       SYN_REPORT            00000000',
            '[  100.020000] /dev/input/event2: EV_ABS       ABS_MT_SLOT           00000000',
            '[  100.020000] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID    ffffffff',
            '[  100.020000] /dev/input/event2: EV_SYN       SYN_REPORT            00000000',
            '[  100.030000] /dev/input/event2: EV_ABS       ABS_MT_SLOT           00000001',
            '[  100.030000] /dev/input/event2: EV_ABS       ABS_MT_TRACKING_ID    ffffffff',
            '[  100.030000] /dev/input/event2: EV_SYN       SYN_REPORT            00000000',
        ]
        touches = parse_getevent_stream(lines)
        by_slot = {}
        for t in touches:
            by_slot.setdefault(t.slot, []).append(t.kind)
        self.assertEqual(by_slot[0], ["down", "up"])
        self.assertEqual(by_slot[1], ["down", "up"])
        # slot 0's finger 1 must never leak slot 1's position (100,100) vs (200,200)
        slot0_down = next(t for t in touches if t.slot == 0 and t.kind == "down")
        slot1_down = next(t for t in touches if t.slot == 1 and t.kind == "down")
        self.assertEqual((slot0_down.x, slot0_down.y), (100, 100))
        self.assertEqual((slot1_down.x, slot1_down.y), (200, 200))


class ParseAxisRangesTest(unittest.TestCase):
    def test_finds_touchscreen_block_and_ignores_distractor(self):
        result = parse_axis_ranges(_REAL_PL_EXCERPT)
        self.assertEqual(result, (1199, 2669))

    def test_no_touch_block_returns_none(self):
        result = parse_axis_ranges('  name:     "gpio-keys"\n')
        self.assertIsNone(result)


class ParseTouchRotationTest(unittest.TestCase):
    def test_reads_orientation_from_viewport_internal_line(self):
        self.assertEqual(parse_touch_rotation(_REAL_DUMPSYS_INPUT_EXCERPT), 1)

    def test_no_viewport_line_returns_none(self):
        self.assertIsNone(parse_touch_rotation("nothing relevant here\n"))


class ApplyRotationTest(unittest.TestCase):
    RAW_X_MAX, RAW_Y_MAX = 1199, 2669

    def test_rotation_0_is_identity(self):
        result = apply_rotation(100, 200, self.RAW_X_MAX, self.RAW_Y_MAX, rotation=0)
        self.assertEqual(result, (100, 200, self.RAW_X_MAX, self.RAW_Y_MAX))

    def test_rotation_90_matches_the_real_jump_button_bug(self):
        # verbatim regression case: a real "jump" button tap landed at raw
        # (123, 2462) on this device (confirmed via `adb shell dumpsys
        # input`'s cached AbsState after the tap). The pre-fix code treated
        # this as already being in logical (landscape) space and scaled it
        # directly, producing (274, 1107) -- the user's actual jump button is
        # at roughly (2416, 1073). Applying rotation=1 first must land within
        # a few percent of that, not the old wrong answer.
        x, y, x_max, y_max = apply_rotation(123, 2462, self.RAW_X_MAX, self.RAW_Y_MAX, rotation=1)
        self.assertEqual((x, y, x_max, y_max), (2462, 1076, self.RAW_Y_MAX, self.RAW_X_MAX))
        # scaled into a 2670x1200 reference resolution (this device's real
        # announced resolution), this should land close to (2416, 1073)
        scaled_x = round(x / x_max * 2670)
        scaled_y = round(y / y_max * 1200)
        self.assertAlmostEqual(scaled_x, 2416, delta=60)
        self.assertAlmostEqual(scaled_y, 1073, delta=15)

    def test_rotation_180_flips_both_axes(self):
        result = apply_rotation(0, 0, self.RAW_X_MAX, self.RAW_Y_MAX, rotation=2)
        self.assertEqual(result, (self.RAW_X_MAX, self.RAW_Y_MAX, self.RAW_X_MAX, self.RAW_Y_MAX))

    def test_rotation_270_is_the_inverse_of_rotation_90(self):
        x, y, x_max, y_max = apply_rotation(123, 2462, self.RAW_X_MAX, self.RAW_Y_MAX, rotation=1)
        # rotating the result back by 270 should recover the original point
        back_x, back_y, _, _ = apply_rotation(x, y, x_max, y_max, rotation=3)
        self.assertEqual((back_x, back_y), (123, 2462))


class SegmentIntoGesturesTest(unittest.TestCase):
    def test_groups_contiguous_down_move_up_per_slot(self):
        touches = [
            RecordedTouch("down", 0, 10, 10, 0.0),
            RecordedTouch("move", 0, 20, 20, 0.1),
            RecordedTouch("up", 0, 20, 20, 0.2),
            RecordedTouch("down", 0, 50, 50, 0.3),
            RecordedTouch("up", 0, 50, 50, 0.35),
        ]
        gestures = segment_into_gestures(touches)
        self.assertEqual(len(gestures), 2)
        self.assertEqual([t.kind for t in gestures[0]], ["down", "move", "up"])
        self.assertEqual([t.kind for t in gestures[1]], ["down", "up"])

    def test_gesture_still_open_at_end_of_stream_is_included(self):
        touches = [RecordedTouch("down", 0, 10, 10, 0.0), RecordedTouch("move", 0, 11, 11, 0.1)]
        gestures = segment_into_gestures(touches)
        self.assertEqual(len(gestures), 1)
        self.assertEqual([t.kind for t in gestures[0]], ["down", "move"])


class GestureToEventsTest(unittest.TestCase):
    def test_rotation_90_reproduces_the_fixed_jump_button_case(self):
        # end-to-end version of ApplyRotationTest.test_rotation_90_matches_the_real_jump_button_bug,
        # through the actual public API a caller uses
        gesture = [RecordedTouch("down", 0, 123, 2462, 0.0), RecordedTouch("up", 0, 123, 2462, 0.03)]
        events = gesture_to_events(gesture, raw_x_max=1199, raw_y_max=2669, ref_w=2670, ref_h=1200, rotation=1)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].x, 2416, delta=60)
        self.assertAlmostEqual(events[0].y, 1073, delta=15)

    def test_rotation_0_is_unchanged_from_no_rotation_support(self):
        gesture = [RecordedTouch("down", 0, 600, 1335, 0.0), RecordedTouch("up", 0, 600, 1335, 0.03)]
        events = gesture_to_events(gesture, raw_x_max=1200, raw_y_max=2670, ref_w=2400, ref_h=5340, rotation=0)
        self.assertEqual((events[0].x, events[0].y), (1200, 2670))

    def test_small_movement_becomes_a_single_tap(self):
        gesture = [
            RecordedTouch("down", 0, 100, 100, 0.0),
            RecordedTouch("move", 0, 103, 101, 0.02),
            RecordedTouch("up", 0, 103, 101, 0.05),
        ]
        events = gesture_to_events(gesture, raw_x_max=1200, raw_y_max=2670, ref_w=1200, ref_h=2670)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, EventKind.TAP)
        self.assertEqual((events[0].x, events[0].y), (100, 100))

    def test_held_still_finger_becomes_press_release_not_a_tap(self):
        # zero movement, but held for 300ms -- a deliberate hold (e.g. a
        # d-pad direction), not an instant tap. Movement alone would
        # misclassify this; duration must be checked too (see
        # _gesture_to_timed_events).
        gesture = [
            RecordedTouch("down", 0, 100, 100, 0.0),
            RecordedTouch("up", 0, 100, 100, 0.30),
        ]
        events = gesture_to_events(gesture, raw_x_max=1200, raw_y_max=2670, ref_w=1200, ref_h=2670)
        self.assertEqual([e.kind for e in events], [EventKind.PRESS, EventKind.WAIT, EventKind.RELEASE])

    def test_brief_still_touch_stays_a_tap(self):
        # the boundary case: zero movement AND short duration (default
        # threshold 150ms) must still be a plain TAP, not every zero-move
        # touch becoming a hold.
        gesture = [RecordedTouch("down", 0, 100, 100, 0.0), RecordedTouch("up", 0, 100, 100, 0.05)]
        events = gesture_to_events(gesture, raw_x_max=1200, raw_y_max=2670, ref_w=1200, ref_h=2670)
        self.assertEqual([e.kind for e in events], [EventKind.TAP])

    def test_large_movement_becomes_press_move_release_with_wait_gaps(self):
        gesture = [
            RecordedTouch("down", 0, 0, 0, 0.0),
            RecordedTouch("move", 0, 600, 0, 0.1),   # 100ms gap
            RecordedTouch("up", 0, 600, 0, 0.2),      # another 100ms gap
        ]
        events = gesture_to_events(gesture, raw_x_max=1200, raw_y_max=2670, ref_w=1200, ref_h=2670)
        kinds = [e.kind for e in events]
        self.assertEqual(kinds, [EventKind.PRESS, EventKind.WAIT, EventKind.MOVE, EventKind.WAIT, EventKind.RELEASE])
        press, _wait1, move, _wait2, release = events
        self.assertEqual((press.x, press.y), (0, 0))
        self.assertEqual((move.x, move.y), (600, 0))
        self.assertIsNone(release.x)

    def test_scales_raw_coordinates_to_reference_resolution(self):
        gesture = [
            RecordedTouch("down", 0, 600, 1335, 0.0),   # midpoint of a 1200x2670 raw panel
            RecordedTouch("up", 0, 600, 1335, 0.05),
        ]
        events = gesture_to_events(gesture, raw_x_max=1200, raw_y_max=2670, ref_w=2400, ref_h=5340)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].x, events[0].y), (1200, 2670))  # scaled 2x

    def test_empty_gesture_returns_no_events(self):
        self.assertEqual(gesture_to_events([], 1200, 2670, 1200, 2670), [])


class MergeGesturesIntoEventsTest(unittest.TestCase):
    def test_two_concurrent_touches_merge_into_one_action_on_separate_pointers(self):
        # "hold right (slot 0) while tapping jump (slot 1)" recorded as one
        # session -- must become ONE combined action, not two, with each
        # touch kept on its own pointer_id (taken from its raw slot). The
        # 200ms hold has ZERO movement but must NOT collapse to a TAP --
        # that's exactly the duration-vs-movement distinction this feature
        # was fixed for (see _gesture_to_timed_events).
        hold_right = [
            RecordedTouch("down", 0, 100, 100, 0.0),
            RecordedTouch("up", 0, 100, 100, 0.20),
        ]
        tap_jump = [
            RecordedTouch("down", 1, 900, 900, 0.05),
            RecordedTouch("up", 1, 900, 900, 0.08),
        ]
        events = merge_gestures_into_events([hold_right, tap_jump], raw_x_max=1200, raw_y_max=2670,
                                             ref_w=1200, ref_h=2670)
        pointer_ids_used = {e.pointer_id for e in events if e.kind != EventKind.WAIT}
        self.assertEqual(pointer_ids_used, {0, 1})
        kinds_and_pointers = [(e.kind, e.pointer_id) for e in events if e.kind != EventKind.WAIT]
        self.assertEqual(kinds_and_pointers, [
            (EventKind.PRESS, 0),    # right: held down at t=0.00
            (EventKind.TAP, 1),      # jump: quick tap at t=0.05, while right is still held
            (EventKind.RELEASE, 0),  # right: released at t=0.20
        ])

    def test_events_are_globally_chronologically_ordered_not_grouped_by_gesture(self):
        # gesture B starts (t=0.01) before gesture A finishes (its PRESS is
        # at t=0.0, RELEASE at t=0.05) -- the merged event order must reflect
        # real time, not "all of A's events then all of B's".
        gesture_a = [
            RecordedTouch("down", 0, 0, 0, 0.0),
            RecordedTouch("move", 0, 500, 0, 0.03),   # forces PRESS/MOVE/RELEASE shape, not a TAP
            RecordedTouch("up", 0, 500, 0, 0.05),
        ]
        gesture_b = [
            RecordedTouch("down", 1, 900, 900, 0.01),
            RecordedTouch("up", 1, 900, 900, 0.02),
        ]
        events = merge_gestures_into_events([gesture_a, gesture_b], raw_x_max=1200, raw_y_max=2670,
                                             ref_w=1200, ref_h=2670)
        non_wait = [(e.kind, e.pointer_id) for e in events if e.kind != EventKind.WAIT]
        self.assertEqual(non_wait, [
            (EventKind.PRESS, 0),    # t=0.00
            (EventKind.TAP, 1),      # t=0.01 (b's single down/up collapses to one TAP)
            (EventKind.MOVE, 0),     # t=0.03
            (EventKind.RELEASE, 0),  # t=0.05
        ])

    def test_sequential_gestures_reusing_the_same_slot_are_kept_separate_in_time(self):
        # the digitizer commonly reuses a raw slot once a finger lifts;
        # two non-overlapping taps on slot 0 must not be merged into one
        # nonsensical double-press.
        first_tap = [RecordedTouch("down", 0, 10, 10, 0.0), RecordedTouch("up", 0, 10, 10, 0.02)]
        second_tap = [RecordedTouch("down", 0, 50, 50, 0.5), RecordedTouch("up", 0, 50, 50, 0.52)]
        events = merge_gestures_into_events([first_tap, second_tap], raw_x_max=1200, raw_y_max=2670,
                                             ref_w=1200, ref_h=2670)
        taps = [e for e in events if e.kind == EventKind.TAP]
        self.assertEqual(len(taps), 2)
        self.assertEqual((taps[0].x, taps[0].y), (10, 10))
        self.assertEqual((taps[1].x, taps[1].y), (50, 50))

    def test_empty_gesture_list_returns_no_events(self):
        self.assertEqual(merge_gestures_into_events([], 1200, 2670, 1200, 2670), [])


if __name__ == "__main__":
    unittest.main()
