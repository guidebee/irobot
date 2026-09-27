from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from irobot_gym_ide import io as project_io
from irobot_gym_ide.connection import LiveConnection

from .latency import run_benchmark
from .policy import HeuristicPolicy, TypeSafePolicy
from .runner import run_session


def cmd_state_demo(args: argparse.Namespace) -> int:
    """Lists a project's actions without connecting to a device or calling TypeSafe."""
    project = project_io.load_project(args.project)
    print(f"Project {project.name!r}: {len(project.actions)} action(s) at {project.host}:{project.port}")
    for name, action in sorted(project.actions.items()):
        description = action.description or "(no description)"
        print(f"  {name:<15} [{action.effective_kind.value:<10}] {description}")
    return 0


def cmd_latency_check(args: argparse.Namespace) -> int:
    project = project_io.load_project(args.project)
    action = project.actions.get(args.action)
    if action is None:
        available = ", ".join(sorted(project.actions)) or "(none defined)"
        print(f"error: project has no action {args.action!r}. Available: {available}")
        return 1

    connection = LiveConnection(project.host, project.port)
    connection.connect()
    try:
        result = run_benchmark(
            connection,
            action,
            project.reference_width,
            project.reference_height,
            samples=args.samples,
            timeout_s=args.timeout_ms / 1000.0,
        )
    finally:
        connection.release_all_held(project.reference_width, project.reference_height)
        connection.disconnect()

    for i, sample in enumerate(result.samples):
        status = "TIMEOUT" if sample.timed_out else f"{sample.round_trip_ms:.0f}ms"
        print(f"  #{i:02d} {status}")
    print(result.summary())
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    if args.policy == "typesafe":
        project = project_io.load_project(args.project)
        policy = TypeSafePolicy({name: a.description for name, a in project.actions.items()})
    else:
        policy = HeuristicPolicy()
    log_path = run_session(
        project_path=args.project,
        policy=policy,
        decision_interval_s=args.decision_interval_ms / 1000.0,
        max_decisions=args.max_decisions,
        artifacts_dir=args.artifacts_dir,
    )
    print(f"Run log: {log_path.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="typesafe-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    state_demo = subparsers.add_parser(
        "state-demo", help="List a project's actions - no device connection, no API calls"
    )
    state_demo.add_argument("project", type=Path, help="Path to the project's project.yaml")

    latency = subparsers.add_parser(
        "latency-check",
        help="Measure round-trip latency for one action against a live device (see latency.py)",
    )
    latency.add_argument("project", type=Path)
    latency.add_argument("--action", default="jump")
    latency.add_argument("--samples", type=int, default=10)
    latency.add_argument("--timeout-ms", type=int, default=2000)

    play = subparsers.add_parser(
        "play", help="Run a live decision loop (connect, observe, ask Jev, act, log) against a device"
    )
    play.add_argument("project", type=Path)
    play.add_argument("--policy", choices=("typesafe", "heuristic"), default="typesafe")
    play.add_argument("--decision-interval-ms", type=int, default=250)
    play.add_argument("--max-decisions", type=int, default=2000)
    play.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "state-demo":
        return cmd_state_demo(args)
    if args.command == "latency-check":
        return cmd_latency_check(args)
    if args.command == "play":
        return cmd_play(args)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
