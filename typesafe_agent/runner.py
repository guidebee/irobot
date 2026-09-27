"""The live decision loop: connect, observe, ask a Policy, act, log, repeat.

Reuses irobot_gym_ide's own project model and LiveConnection rather than
re-deriving the wire protocol or action-execution semantics (hold_start/
hold_stop/momentary/macro PrimitiveEvent sequencing already lives in
connection.py's `LiveConnection.run_action` - see its module and method
docstrings). This module's only job is the decision loop itself: pull the
latest frame, build an Observation, ask a Policy which named action to run
next, run it, and record what happened.

Every decision considers the project's full action set (including '*_start'/
'*_stop' pairs) rather than a fixed macro vocabulary like typesafe-mario's,
since a Gym IDE project's action names are project-defined, not universal.
A '*_start'/'*_stop' naming convention is assumed for hold bookkeeping (see
`_update_holds`) - true for the mario_platformer example project, but not
guaranteed by the schema itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from irobot_gym_ide import io as project_io
from irobot_gym_ide.connection import LiveConnection

from .policy import Decision, Policy

_HOLD_START_SUFFIX = "_start"
_HOLD_STOP_SUFFIX = "_stop"


@dataclass(frozen=True)
class Observation:
    decision_index: int
    elapsed_ms: float
    frame_changed: bool
    stalled_decisions: int
    active_holds: tuple

    def to_state(self) -> dict:
        return {
            "objective": "Reach the level's end without dying.",
            "decision_index": self.decision_index,
            "elapsed_ms": round(self.elapsed_ms),
            "frame_changed_since_last_decision": self.frame_changed,
            "stalled_decisions": self.stalled_decisions,
            "currently_held_actions": list(self.active_holds),
        }


def _wait_for_thumbnail(connection: LiveConnection, timeout_s: float = 10.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        thumb = connection.latest_thumbnail()
        if thumb is not None:
            return thumb
        time.sleep(0.05)
    raise TimeoutError(
        f"no frame received from irobot's video port within {timeout_s:.0f}s "
        "(is irobot running and connected to a device?)"
    )


def _update_holds(active_holds: set, action_name: str) -> None:
    if action_name.endswith(_HOLD_START_SUFFIX):
        active_holds.add(action_name[: -len(_HOLD_START_SUFFIX)])
    elif action_name.endswith(_HOLD_STOP_SUFFIX):
        active_holds.discard(action_name[: -len(_HOLD_STOP_SUFFIX)])


def run_session(
    *,
    project_path: Path,
    policy: Policy,
    decision_interval_s: float,
    max_decisions: int,
    artifacts_dir: Path,
) -> Path:
    project = project_io.load_project(project_path)
    action_names = sorted(project.actions)
    if not action_names:
        raise ValueError(f"project at {project_path} defines no actions")

    connection = LiveConnection(project.host, project.port)
    connection.connect()
    active_holds: set = set()

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = artifacts_dir / f"run-{timestamp}.jsonl"

    start = time.monotonic()
    _, _, _, last_phash = _wait_for_thumbnail(connection)
    stalled_decisions = 0

    try:
        with log_path.open("w", encoding="utf-8") as log:
            for decision_index in range(max_decisions):
                tick_start = time.monotonic()
                _, _, _, phash = _wait_for_thumbnail(connection)
                frame_changed = phash != last_phash
                stalled_decisions = 0 if frame_changed else stalled_decisions + 1
                last_phash = phash

                observation = Observation(
                    decision_index=decision_index,
                    elapsed_ms=(time.monotonic() - start) * 1000,
                    frame_changed=frame_changed,
                    stalled_decisions=stalled_decisions,
                    active_holds=tuple(sorted(active_holds)),
                )
                decision: Decision = policy.choose(observation, action_names)
                action = project.actions[decision.action_name]
                skipped = connection.run_action(
                    action, project.reference_width, project.reference_height
                )
                _update_holds(active_holds, decision.action_name)

                record = {
                    "decision": decision_index,
                    "observation": observation.to_state(),
                    "action": decision.action_name,
                    "confidence": decision.confidence,
                    "latency_ms": decision.latency_ms,
                    "skipped_events": skipped,
                }
                log.write(json.dumps(record, separators=(",", ":")) + "\n")
                log.flush()
                stall_note = " (stalled)" if stalled_decisions else ""
                print(
                    f"#{decision_index:04d} action={decision.action_name:<15} "
                    f"confidence={decision.confidence:.2f} "
                    f"latency={decision.latency_ms:.0f}ms{stall_note}"
                )

                remaining = decision_interval_s - (time.monotonic() - tick_start)
                if remaining > 0:
                    time.sleep(remaining)
    finally:
        connection.release_all_held(project.reference_width, project.reference_height)
        connection.disconnect()
        close = getattr(policy, "close", None)
        if callable(close):
            close()

    return log_path
