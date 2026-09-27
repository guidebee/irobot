import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from typesafe_agent.cli import build_parser, cmd_state_demo

EXAMPLE_PROJECT = (
    Path(__file__).resolve().parents[2] / "irobot_gym_ide" / "examples" / "mario_platformer" / "project.yaml"
)


class StateDemoTests(unittest.TestCase):
    def test_lists_mario_platformer_actions_with_no_network(self):
        self.assertTrue(EXAMPLE_PROJECT.exists(), f"example project missing at {EXAMPLE_PROJECT}")
        args = build_parser().parse_args(["state-demo", str(EXAMPLE_PROJECT)])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = cmd_state_demo(args)
        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        for expected_action in ("jump", "right_start", "run_start", "long_jump"):
            self.assertIn(expected_action, output)


if __name__ == "__main__":
    unittest.main()
