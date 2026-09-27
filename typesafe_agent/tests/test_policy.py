import unittest

from typesafe_agent.policy import HeuristicPolicy
from typesafe_agent.runner import Observation, _update_holds


def _observation(stalled_decisions: int = 0, active_holds=()) -> Observation:
    return Observation(
        decision_index=0,
        elapsed_ms=0.0,
        frame_changed=False,
        stalled_decisions=stalled_decisions,
        active_holds=tuple(active_holds),
    )


class HeuristicPolicyTests(unittest.TestCase):
    ACTIONS = ("left_start", "left_stop", "right_start", "right_stop", "jump", "run_start", "run_stop")

    def test_holds_default_action_when_not_stalled(self):
        policy = HeuristicPolicy(default_action="right_start", fallback_action="jump", stall_threshold=3)
        decision = policy.choose(_observation(stalled_decisions=0), self.ACTIONS)
        self.assertEqual(decision.action_name, "right_start")
        self.assertEqual(decision.probabilities["right_start"], 1.0)
        self.assertEqual(sum(decision.probabilities.values()), 1.0)

    def test_falls_back_once_stalled(self):
        policy = HeuristicPolicy(default_action="right_start", fallback_action="jump", stall_threshold=3)
        decision = policy.choose(_observation(stalled_decisions=3), self.ACTIONS)
        self.assertEqual(decision.action_name, "jump")

    def test_falls_back_to_first_action_if_default_missing(self):
        policy = HeuristicPolicy(default_action="does_not_exist")
        decision = policy.choose(_observation(), ("left_start", "right_start"))
        self.assertEqual(decision.action_name, "left_start")


class ObservationStateTests(unittest.TestCase):
    def test_to_state_shape(self):
        observation = _observation(stalled_decisions=2, active_holds=("right", "run"))
        state = observation.to_state()
        self.assertEqual(state["stalled_decisions"], 2)
        self.assertEqual(state["currently_held_actions"], ["right", "run"])
        self.assertIn("objective", state)


class UpdateHoldsTests(unittest.TestCase):
    def test_start_adds_hold(self):
        holds = set()
        _update_holds(holds, "right_start")
        self.assertEqual(holds, {"right"})

    def test_stop_removes_hold(self):
        holds = {"right"}
        _update_holds(holds, "right_stop")
        self.assertEqual(holds, set())

    def test_momentary_action_does_not_touch_holds(self):
        holds = {"right"}
        _update_holds(holds, "jump")
        self.assertEqual(holds, {"right"})


if __name__ == "__main__":
    unittest.main()
