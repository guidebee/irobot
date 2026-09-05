"""classify_session tests -- pure model, no Qt/socket/device."""
import unittest

from ..hud_classifier import (
    build_game_run, classify_session, compare_replay_durations, diff_classifications, propose_actions,
    propose_combos,
)
from ..model import (
    Action, EventKind, GameplaySession, HudRegion, HudRegionCombo, PrimitiveEvent, RunNodeKind, SessionSegment,
)


def _regions(*regions) -> dict:
    return {r.name: r for r in regions}


def _combos(*combos) -> dict:
    return {c.name: c for c in combos}


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


class ComboClassificationTest(unittest.TestCase):
    def _right_and_jump_regions(self):
        return _regions(
            HudRegion(name="right_button", x=0, y=0, width=10, height=10, action_name="move_right"),
            HudRegion(name="jump_button", x=100, y=0, width=10, height=10, action_name="jump"),
        )

    def test_overlapping_regions_fold_into_one_combo_segment_when_defined(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),      # right_button starts
            PrimitiveEvent(kind=EventKind.PRESS, x=105, y=5, pointer_id=1),    # jump_button starts, overlapping
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),              # jump_button ends
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),              # right_button ends
        ]
        session = GameplaySession(name="s", events=events)
        regions = self._right_and_jump_regions()
        combos = _combos(HudRegionCombo(name="right_jump", region_names=["right_button", "jump_button"],
                                         action_name="right_jump"))
        segments = classify_session(session, regions, combos)
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        self.assertEqual((seg.start_index, seg.end_index, seg.action_name, seg.label), (0, 4, "right_jump", "right_jump"))

    def test_overlap_without_a_matching_combo_falls_back_to_separate_segments(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.PRESS, x=105, y=5, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        regions = self._right_and_jump_regions()
        logs = []
        segments = classify_session(session, regions, {}, on_log=logs.append)
        self.assertEqual(len(segments), 2)
        self.assertEqual({(s.start_index, s.end_index, s.action_name) for s in segments},
                          {(0, 4, "move_right"), (1, 3, "jump")})
        self.assertTrue(any("no matching HudRegionCombo" in line for line in logs))

    def test_three_way_overlap_does_not_partially_match_a_two_region_combo(self):
        third = HudRegion(name="shield_button", x=200, y=0, width=10, height=10, action_name="shield")
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),      # right_button
            PrimitiveEvent(kind=EventKind.PRESS, x=105, y=5, pointer_id=1),    # jump_button
            PrimitiveEvent(kind=EventKind.PRESS, x=205, y=5, pointer_id=2),    # shield_button, all overlapping
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=2),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        regions = self._right_and_jump_regions()
        regions["shield_button"] = third
        combos = _combos(HudRegionCombo(name="right_jump", region_names=["right_button", "jump_button"],
                                         action_name="right_jump"))
        segments = classify_session(session, regions, combos)
        # the combo's region set {right_button, jump_button} != the cluster's {right_button, jump_button,
        # shield_button}, so no combo applies -- all three classified separately, not partially merged.
        self.assertEqual(len(segments), 3)
        self.assertEqual({s.action_name for s in segments}, {"move_right", "jump", "shield"})

    def test_repeated_taps_nested_in_a_hold_all_fold_into_one_combo_span(self):
        # holding right_button the whole time while tapping jump_button three times inside that hold --
        # the real "run and mash jump" pattern that originally produced spurious overlap warnings.
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),   # 0: right_button starts
            PrimitiveEvent(kind=EventKind.TAP, x=105, y=5),                 # 1: jump tap 1
            PrimitiveEvent(kind=EventKind.TAP, x=105, y=5),                 # 2: jump tap 2
            PrimitiveEvent(kind=EventKind.TAP, x=105, y=5),                 # 3: jump tap 3
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),           # 4: right_button ends
        ]
        session = GameplaySession(name="s", events=events)
        regions = self._right_and_jump_regions()
        combos = _combos(HudRegionCombo(name="right_jump", region_names=["right_button", "jump_button"],
                                         action_name="right_jump"))
        segments = classify_session(session, regions, combos)
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        self.assertEqual((seg.start_index, seg.end_index, seg.action_name), (0, 5, "right_jump"))


class HoldRegionClassificationTest(unittest.TestCase):
    def _right_hold_region(self):
        return HudRegion(name="right_button", x=0, y=0, width=10, height=10,
                          action_name="right_start", release_action_name="right_stop")

    def test_solo_hold_produces_start_and_stop_bookend_segments(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),   # 0
            PrimitiveEvent(kind=EventKind.WAIT, frames=20),                 # 1
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),           # 2
        ]
        session = GameplaySession(name="s", events=events)
        regions = _regions(self._right_hold_region())
        segments = classify_session(session, regions)
        self.assertEqual([(s.start_index, s.end_index, s.action_name) for s in segments],
                          [(0, 1, "right_start"), (2, 3, "right_stop")])

    def test_tap_on_hold_region_produces_both_bookends_at_the_same_index(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(self._right_hold_region())
        segments = classify_session(session, regions)
        self.assertEqual([(s.start_index, s.end_index, s.action_name) for s in segments],
                          [(0, 1, "right_start"), (0, 1, "right_stop")])

    def test_hold_nested_in_unmatched_overlap_still_bookends(self):
        # right held the whole time, jump tapped inside it, but no combo defined --
        # falls back to separate classification, and the hold half still bookends.
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),      # 0: right starts
            PrimitiveEvent(kind=EventKind.TAP, x=105, y=5),                    # 1: jump tap
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),              # 2: right ends
        ]
        session = GameplaySession(name="s", events=events)
        regions = _regions(self._right_hold_region(),
                            HudRegion(name="jump_button", x=100, y=0, width=10, height=10, action_name="jump"))
        segments = classify_session(session, regions, {})
        self.assertEqual({(s.start_index, s.end_index, s.action_name) for s in segments},
                          {(0, 1, "right_start"), (1, 2, "jump"), (2, 3, "right_stop")})

    def test_hold_nested_in_matched_combo_still_folds_into_one_segment(self):
        # unchanged from the plain-region case -- an explicit combo still wins over
        # bookend-splitting, since the combo names one action for the whole span.
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.TAP, x=105, y=5),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        regions = _regions(self._right_hold_region(),
                            HudRegion(name="jump_button", x=100, y=0, width=10, height=10, action_name="jump"))
        combos = _combos(HudRegionCombo(name="right_jump", region_names=["right_button", "jump_button"],
                                         action_name="right_jump"))
        segments = classify_session(session, regions, combos)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].action_name, "right_jump")


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


class ProposeActionsTest(unittest.TestCase):
    def test_classified_segment_with_no_existing_action_is_proposed(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump"))
        session.segments = classify_session(session, regions)
        proposals = propose_actions(session, project_actions={})
        self.assertEqual(set(proposals), {"jump"})
        self.assertEqual(len(proposals["jump"].events), 1)
        self.assertEqual(proposals["jump"].events[0].kind, EventKind.TAP)

    def test_classified_segment_with_existing_action_is_not_overwritten(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump"))
        session.segments = classify_session(session, regions)
        proposals = propose_actions(session, project_actions={"jump": Action(name="jump")})
        self.assertEqual(proposals, {})

    def test_unclassified_tap_gets_a_placeholder_name(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=999, y=999)])
        session.segments = classify_session(session, {})
        proposals = propose_actions(session, project_actions={})
        self.assertEqual(set(proposals), {"unknown_1"})
        self.assertEqual(proposals["unknown_1"].events[0].x, 999)

    def test_multiple_unclassified_gestures_get_sequential_names_skipping_taken_ones(self):
        session = GameplaySession(name="s", events=[
            PrimitiveEvent(kind=EventKind.TAP, x=1, y=1),
            PrimitiveEvent(kind=EventKind.TAP, x=2, y=2),
        ])
        session.segments = classify_session(session, {})
        proposals = propose_actions(session, project_actions={"unknown_1": Action(name="unknown_1")})
        self.assertEqual(set(proposals), {"unknown_2", "unknown_3"})

    def test_press_release_gesture_covered_by_bookend_segments_is_not_reproposed_as_unknown(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.WAIT, frames=10),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        regions = _regions(HudRegion(name="right_button", x=0, y=0, width=10, height=10,
                                      action_name="right_start", release_action_name="right_stop"))
        session.segments = classify_session(session, regions)
        proposals = propose_actions(session, project_actions={})
        self.assertEqual(set(proposals), {"right_start", "right_stop"})

    def test_proposed_events_are_a_deep_copy_not_shared_with_the_session(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump"))
        session.segments = classify_session(session, regions)
        proposals = propose_actions(session, project_actions={})
        proposals["jump"].events[0].x = 12345
        self.assertEqual(session.events[0].x, 5)

    def test_new_name_whose_events_look_like_an_existing_action_is_flagged_as_a_possible_duplicate(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)])
        regions = _regions(HudRegion(name="alt_jump_button", x=90, y=90, width=20, height=20, action_name="hop"))
        session.segments = classify_session(session, regions)
        existing = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=105, y=103)])}
        proposals = propose_actions(session, project_actions=existing)
        self.assertEqual(set(proposals), {"hop"})
        self.assertIn("possible duplicate of 'jump'", proposals["hop"].description)

    def test_events_that_dont_resemble_any_existing_action_are_not_flagged(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump"))
        session.segments = classify_session(session, regions)
        existing = {"attack": Action(name="attack", events=[PrimitiveEvent(kind=EventKind.TAP, x=900, y=900)])}
        proposals = propose_actions(session, project_actions=existing)
        self.assertNotIn("possible duplicate", proposals["jump"].description)

    def test_unknown_proposal_description_and_log_include_coordinates(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=42, y=99)])
        session.segments = classify_session(session, {})
        logs = []
        proposals = propose_actions(session, project_actions={}, on_log=logs.append)
        self.assertIn("(42, 99)", proposals["unknown_1"].description)
        self.assertTrue(any("(42, 99)" in line for line in logs))

    def test_classified_proposal_description_includes_coordinates(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=7, y=8)])
        regions = _regions(HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump"))
        session.segments = classify_session(session, regions)
        proposals = propose_actions(session, project_actions={})
        self.assertIn("(7, 8)", proposals["jump"].description)


class PatternMatchAmbiguityTest(unittest.TestCase):
    def test_classify_session_logs_when_a_gesture_matches_multiple_actions_within_tolerance(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=100, y=100)])
        existing = {
            "far": Action(name="far", events=[PrimitiveEvent(kind=EventKind.TAP, x=115, y=100)]),
            "near": Action(name="near", events=[PrimitiveEvent(kind=EventKind.TAP, x=103, y=101)]),
        }
        logs = []
        segments = classify_session(session, {}, project_actions=existing, on_log=logs.append)
        self.assertEqual(segments[0].action_name, "near")
        self.assertTrue(any("matched 2 existing actions" in line for line in logs))


class DiffClassificationsTest(unittest.TestCase):
    def test_unchanged_segment_counted_as_unchanged(self):
        old = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        new = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        self.assertEqual(diff_classifications(old, new), {"unchanged": 1, "changed": 0, "added": 0, "removed": 0})

    def test_same_span_different_action_counted_as_changed(self):
        old = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        new = [SessionSegment(start_index=0, end_index=1, action_name="jump_v2")]
        self.assertEqual(diff_classifications(old, new), {"unchanged": 0, "changed": 1, "added": 0, "removed": 0})

    def test_new_span_counted_as_added(self):
        old = []
        new = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        self.assertEqual(diff_classifications(old, new), {"unchanged": 0, "changed": 0, "added": 1, "removed": 0})

    def test_missing_span_counted_as_removed(self):
        old = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        new = []
        self.assertEqual(diff_classifications(old, new), {"unchanged": 0, "changed": 0, "added": 0, "removed": 1})


class ProposeCombosTest(unittest.TestCase):
    def _right_and_jump_regions(self):
        return _regions(
            HudRegion(name="right_button", x=0, y=0, width=10, height=10, action_name="move_right"),
            HudRegion(name="jump_button", x=100, y=0, width=10, height=10, action_name="jump"),
        )

    def test_recurring_unmatched_concurrent_cluster_is_proposed_as_a_combo(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.PRESS, x=105, y=5, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        proposals = propose_combos(session, self._right_and_jump_regions())
        self.assertEqual(set(proposals), {"jump_button+right_button"})
        combo = proposals["jump_button+right_button"]
        self.assertEqual(set(combo.region_names), {"right_button", "jump_button"})
        self.assertEqual(combo.action_name, "jump_button+right_button")

    def test_already_defined_combo_is_not_reproposed(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5, pointer_id=0),
            PrimitiveEvent(kind=EventKind.PRESS, x=105, y=5, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        combos = _combos(HudRegionCombo(name="right_jump", region_names=["right_button", "jump_button"],
                                         action_name="right_jump"))
        proposals = propose_combos(session, self._right_and_jump_regions(), combos)
        self.assertEqual(proposals, {})

    def test_solo_non_overlapping_gestures_are_not_proposed_as_a_combo(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        proposals = propose_combos(session, self._right_and_jump_regions())
        self.assertEqual(proposals, {})


class BuildGameRunTest(unittest.TestCase):
    def test_empty_segments_produce_an_empty_run(self):
        session = GameplaySession(name="s", events=[])
        run = build_game_run(session, "my_run")
        self.assertEqual(run.name, "my_run")
        self.assertEqual(run.nodes, {})
        self.assertEqual(run.edges, [])

    def test_one_segment_produces_one_action_node_and_no_delay(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        session.segments = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        run = build_game_run(session, "my_run")
        action_nodes = [n for n in run.nodes.values() if n.kind == RunNodeKind.ACTION]
        self.assertEqual(len(action_nodes), 1)
        self.assertEqual(action_nodes[0].action_name, "jump")
        self.assertEqual(run.edges, [])

    def test_gap_between_segments_becomes_a_delay_node(self):
        events = [
            PrimitiveEvent(kind=EventKind.TAP, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=15),
            PrimitiveEvent(kind=EventKind.TAP, x=9, y=9),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [
            SessionSegment(start_index=0, end_index=1, action_name="jump"),
            SessionSegment(start_index=2, end_index=3, action_name="attack"),
        ]
        run = build_game_run(session, "my_run")
        delay_nodes = [n for n in run.nodes.values() if n.kind == RunNodeKind.DELAY]
        action_nodes = sorted((n for n in run.nodes.values() if n.kind == RunNodeKind.ACTION),
                               key=lambda n: n.x)
        self.assertEqual(len(delay_nodes), 1)
        self.assertEqual(delay_nodes[0].frames, 15)
        self.assertEqual([n.action_name for n in action_nodes], ["jump", "attack"])
        # jump -> delay -> attack, chained
        self.assertEqual(len(run.edges), 2)
        self.assertEqual(len(run.roots()), 1)

    def test_zero_gap_chains_actions_directly_with_no_delay_node(self):
        session = GameplaySession(name="s", events=[
            PrimitiveEvent(kind=EventKind.TAP, x=5, y=5),
            PrimitiveEvent(kind=EventKind.TAP, x=9, y=9),
        ])
        session.segments = [
            SessionSegment(start_index=0, end_index=1, action_name="jump"),
            SessionSegment(start_index=1, end_index=2, action_name="attack"),
        ]
        run = build_game_run(session, "my_run")
        self.assertEqual([n.kind for n in run.nodes.values()], [RunNodeKind.ACTION, RunNodeKind.ACTION])
        self.assertEqual(len(run.edges), 1)

    def test_result_validates_cleanly_against_a_matching_action_dict(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        session.segments = [SessionSegment(start_index=0, end_index=1, action_name="jump")]
        run = build_game_run(session, "my_run")
        self.assertEqual(run.validate({"jump": Action(name="jump")}), [])

    def test_no_project_actions_means_no_catchup_delay(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=50),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="right_jump")]
        run = build_game_run(session, "my_run")
        self.assertEqual([n.kind for n in run.nodes.values()], [RunNodeKind.ACTION])

    def test_action_shorter_than_recorded_span_gets_a_catchup_delay_node(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=50),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="right_jump")]
        actions = {"right_jump": Action(name="right_jump", events=[PrimitiveEvent(kind=EventKind.WAIT, frames=6)])}
        run = build_game_run(session, "my_run", actions)
        nodes = sorted(run.nodes.values(), key=lambda n: n.x)
        self.assertEqual([n.kind for n in nodes], [RunNodeKind.ACTION, RunNodeKind.DELAY])
        self.assertEqual(nodes[1].frames, 44)
        self.assertEqual(len(run.edges), 1)
        self.assertEqual(len(run.roots()), 1)

    def test_action_at_least_as_long_as_recorded_span_gets_no_catchup_delay(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=5),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="a")]
        actions = {"a": Action(name="a", events=[PrimitiveEvent(kind=EventKind.WAIT, frames=20)])}
        run = build_game_run(session, "my_run", actions)
        self.assertEqual([n.kind for n in run.nodes.values()], [RunNodeKind.ACTION])


class CompareReplayDurationsTest(unittest.TestCase):
    def test_matching_action_timing_reports_no_mismatch(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=10),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="hold")]
        actions = {"hold": Action(name="hold", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=10),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ])}
        result = compare_replay_durations(session, actions)
        self.assertEqual(result["raw_frames"], 10)
        self.assertEqual(result["classified_frames"], 10)
        self.assertEqual(result["mismatches"], [])

    def test_a_long_recorded_span_replayed_by_a_short_canned_action_is_flagged(self):
        # the real bug this catches: a combo/action's own canned timing is much shorter
        # than how long the classified span actually took to record.
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=300),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="run_and_jump",
                                            label="right_jump")]
        actions = {"run_and_jump": Action(name="run_and_jump", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=6),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ])}
        result = compare_replay_durations(session, actions)
        self.assertEqual(result["raw_frames"], 300)
        self.assertEqual(result["classified_frames"], 6)
        self.assertEqual(result["mismatches"], [("right_jump", "run_and_jump", 300, 6)])

    def test_small_differences_within_threshold_are_not_flagged(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=10),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ]
        session = GameplaySession(name="s", events=events)
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="hold")]
        actions = {"hold": Action(name="hold", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=11),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ])}
        result = compare_replay_durations(session, actions, mismatch_threshold_frames=3)
        self.assertEqual(result["mismatches"], [])

    def test_missing_action_counts_as_zero_frames_and_can_still_be_flagged(self):
        session = GameplaySession(name="s", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=5, y=5),
            PrimitiveEvent(kind=EventKind.WAIT, frames=50),
            PrimitiveEvent(kind=EventKind.RELEASE),
        ])
        session.segments = [SessionSegment(start_index=0, end_index=3, action_name="missing")]
        result = compare_replay_durations(session, {})
        self.assertEqual(result["classified_frames"], 0)
        self.assertEqual(result["mismatches"], [("missing", "missing", 50, 0)])


class PatternMatchClassificationTest(unittest.TestCase):
    def test_gesture_outside_every_region_matches_an_existing_action_by_pattern(self):
        # jump_button tap recorded again, at a slightly different pixel (jitter) and
        # nowhere near any defined HudRegion -- still recognized via the action library.
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=903, y=1802)])
        existing = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=900, y=1800)])}
        segments = classify_session(session, {}, project_actions=existing)
        self.assertEqual([(s.start_index, s.end_index, s.action_name) for s in segments], [(0, 1, "jump")])

    def test_hud_region_still_wins_over_a_pattern_match(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        regions = _regions(HudRegion(name="jump_button", x=0, y=0, width=10, height=10, action_name="jump_v2"))
        existing = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])}
        segments = classify_session(session, regions, project_actions=existing)
        self.assertEqual([s.action_name for s in segments], ["jump_v2"])

    def test_hold_gesture_matches_split_start_stop_actions_by_pattern(self):
        events = [
            PrimitiveEvent(kind=EventKind.PRESS, x=742, y=1063, pointer_id=0),
            PrimitiveEvent(kind=EventKind.WAIT, frames=15),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0),
        ]
        session = GameplaySession(name="s", events=events)
        existing = {
            "right_start": Action(name="right_start", events=[
                PrimitiveEvent(kind=EventKind.PRESS, x=745, y=1060, pointer_id=0)]),
            "right_stop": Action(name="right_stop", events=[PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=0)]),
        }
        segments = classify_session(session, {}, project_actions=existing)
        self.assertEqual([(s.start_index, s.end_index, s.action_name) for s in segments],
                          [(0, 1, "right_start"), (2, 3, "right_stop")])

    def test_no_match_leaves_gesture_unclassified(self):
        session = GameplaySession(name="s", events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)])
        existing = {"jump": Action(name="jump", events=[PrimitiveEvent(kind=EventKind.TAP, x=900, y=1800)])}
        segments = classify_session(session, {}, project_actions=existing)
        self.assertEqual(segments, [])


if __name__ == "__main__":
    unittest.main()
