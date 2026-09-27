"""Jev's Choice judgment over one decision-loop observation.

Unlike typesafe-mario's RAM-derived telemetry (exact position, velocity, a
local collision grid), the observation here is deliberately thin: iRobot's
AgentManager streams a frame + perceptual hash, not structured game state,
and no reward/HUD/OCR extraction exists yet (see
docs/opengym_implementation_plan.md Sec 8, "not yet implemented" as of this
writing). Jev picks blind, informed only by whether the screen visibly
changed since the last decision and which holds it left active - enough to
validate the control loop end-to-end, not a real playing strategy. See
runner.py's module docstring for the fuller picture.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Decision:
    action_name: str
    confidence: float
    latency_ms: float
    probabilities: Mapping[str, float]


class Observation(Protocol):
    def to_state(self) -> dict: ...
    stalled_decisions: int


class Policy(Protocol):
    def choose(self, observation: Observation, action_names: Sequence[str]) -> Decision: ...


class TypeSafePolicy:
    """Asks TypeSafe's Jev model to pick the next named action from a project's ActionMap."""

    def __init__(self, action_descriptions: Mapping[str, str] | None = None) -> None:
        try:
            from typesafe_sdk import Choice, TypeSafeClient
        except ImportError as exc:
            raise RuntimeError(
                "typesafe-sdk is not installed. Install it before using the 'typesafe' policy."
            ) from exc
        self._Choice = Choice
        self._client = TypeSafeClient()
        self._action_descriptions = dict(action_descriptions or {})

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def choose(self, observation: Observation, action_names: Sequence[str]) -> Decision:
        criteria = {name: self._action_descriptions.get(name, name) for name in action_names}
        question = self._Choice(
            instructions={
                "question": "Which named action should run next?",
                "goal": "Reach the level's end without dying.",
                "observability": (
                    "You cannot see the screen directly. `frame_changed_since_last_decision` "
                    "and `stalled_decisions` are the only feedback on whether the last action "
                    "had any visible effect; a rising `stalled_decisions` likely means the "
                    "current hold is blocked and a different action (e.g. a jump) is needed."
                ),
                "holds": (
                    "`currently_held_actions` lists holds already active from a previous "
                    "'*_start' decision. Nothing stays held on its own: issue the matching "
                    "'*_stop' before switching direction, and re-issue any '*_start' hold "
                    "you still want on this decision too."
                ),
            },
            criteria=criteria,
        )
        started = time.perf_counter()
        response = self._client.system_one(
            state=observation.to_state(), questions={"next_action": question}
        )
        latency_ms = (time.perf_counter() - started) * 1000
        answer = self._answer(response, "next_action")
        probabilities = {str(k): float(v) for k, v in dict(answer.probabilities).items()}
        return Decision(
            action_name=str(answer.choice),
            confidence=float(answer.confidence),
            latency_ms=latency_ms,
            probabilities=probabilities,
        )

    @staticmethod
    def _answer(response: Any, question_id: str) -> Any:
        choices = getattr(response, "choices", None)
        if choices is not None and question_id in choices:
            return choices[question_id]
        answers = getattr(response, "answers", None)
        if answers is not None and question_id in answers:
            return answers[question_id]
        raise KeyError(f"TypeSafe response omitted {question_id!r}")


class HeuristicPolicy:
    """Offline smoke-test policy - no API key or network needed.

    Not a real playing strategy: holds a configured default action, and
    switches to `fallback_action` (typically a jump) once
    `stalled_decisions` crosses `stall_threshold`, so the control loop
    (connect, decide, run_action, log) can be exercised end-to-end without
    TypeSafe in the loop.
    """

    def __init__(
        self,
        default_action: str = "right_start",
        fallback_action: str = "jump",
        stall_threshold: int = 3,
    ) -> None:
        self.default_action = default_action
        self.fallback_action = fallback_action
        self.stall_threshold = stall_threshold

    def choose(self, observation: Observation, action_names: Sequence[str]) -> Decision:
        allowed = set(action_names)
        action = self.default_action if self.default_action in allowed else action_names[0]
        if observation.stalled_decisions >= self.stall_threshold and self.fallback_action in allowed:
            action = self.fallback_action
        return Decision(
            action_name=action,
            confidence=1.0,
            latency_ms=0.0,
            probabilities={name: float(name == action) for name in action_names},
        )
