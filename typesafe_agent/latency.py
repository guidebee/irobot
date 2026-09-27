"""Round-trip control-loop latency benchmark.

docs/opengym_implementation_plan.md Sec 1.1 flags measuring this as the very
first validation step before building reward/adapter machinery, and notes
nobody had measured it for the agent path yet: "device screen change -> ...
-> policy inference -> ... -> Android input dispatch -> ... the *next*
frame the agent will see", estimated at 100-300ms round-trip with no real
measurement behind that number. This gives a real one for one action at a
time, against a live connection.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from irobot_gym_ide.connection import LiveConnection
from irobot_gym_ide.model import Action


@dataclass(frozen=True)
class LatencySample:
    round_trip_ms: float
    timed_out: bool


def measure_action_latency(
    connection: LiveConnection,
    action: Action,
    ref_w: int,
    ref_h: int,
    *,
    timeout_s: float = 2.0,
    settle_s: float = 0.2,
) -> LatencySample:
    """Sends `action`, then polls the video port's phash until it changes.

    Not exact frame-accurate timing: the video channel is push-only and
    unsolicited (see connection.py's module docstring), so this measures
    wall-clock time to the next *observed* phash change, not the device's
    true reaction frame - close enough to size out whether a genre's control
    loop is even in reach, not a precision instrument.
    """
    thumb = connection.latest_thumbnail()
    baseline_phash = thumb[3] if thumb else b""
    time.sleep(settle_s)  # let any in-flight frame settle before starting the clock

    start = time.perf_counter()
    connection.run_action(action, ref_w, ref_h)
    deadline = start + timeout_s
    while time.perf_counter() < deadline:
        thumb = connection.latest_thumbnail()
        if thumb is not None and thumb[3] != baseline_phash:
            return LatencySample(round_trip_ms=(time.perf_counter() - start) * 1000, timed_out=False)
        time.sleep(0.005)
    return LatencySample(round_trip_ms=timeout_s * 1000, timed_out=True)


@dataclass(frozen=True)
class BenchmarkResult:
    samples: list
    valid_ms: list
    timeouts: int

    def summary(self) -> str:
        if not self.valid_ms:
            return f"0/{len(self.samples)} responded ({self.timeouts} timed out)"
        return (
            f"{len(self.valid_ms)}/{len(self.samples)} responded - "
            f"min={min(self.valid_ms):.0f}ms mean={statistics.mean(self.valid_ms):.0f}ms "
            f"max={max(self.valid_ms):.0f}ms"
            + (f" ({self.timeouts} timed out)" if self.timeouts else "")
        )


def run_benchmark(
    connection: LiveConnection,
    action: Action,
    ref_w: int,
    ref_h: int,
    *,
    samples: int = 10,
    timeout_s: float = 2.0,
) -> BenchmarkResult:
    results = [
        measure_action_latency(connection, action, ref_w, ref_h, timeout_s=timeout_s)
        for _ in range(samples)
    ]
    valid_ms = [r.round_trip_ms for r in results if not r.timed_out]
    timeouts = sum(1 for r in results if r.timed_out)
    return BenchmarkResult(samples=results, valid_ms=valid_ms, timeouts=timeouts)
