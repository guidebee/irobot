"""Executes a GameRun graph against a live connection.

Walks the node DAG: when a node finishes, every one of its outgoing edges
fires concurrently (fork), and a node only starts once every one of its
incoming edges has fired (AND-join) -- plain fork/join, no special-casing,
for every node kind except REPEAT. A REPEAT node instead runs its "body"
edge's target as its own independent fork/join subgraph, to completion,
`times` times in a row (so a fork/join inside the body works exactly like
anywhere else, and a REPEAT nested inside another REPEAT's body just works
too, each with its own fresh join-counters), then fires its single "after"
edge once. See model.py's GameRun docstring for the node/edge vocabulary
this executes.

Not itself Gym env stepping -- this is the IDE's own "run it and watch the
log" loop, same spirit as MainWindow's existing single-action Test button,
just for a whole graph of actions instead of one.

Known limitation: join-counting is keyed off the *whole* graph's static
in-degree (GameRun.incoming()), computed fresh per subgraph invocation. A
node that is reachable both from inside a REPEAT's body and from outside it
has an in-degree that doesn't mean what either caller expects and will
likely never fire (its pending-edge count includes an edge that never fires
during that particular invocation) -- keep body nodes private to their
REPEAT, same as you would not point two different Actions at fields of a
third Action's internal state.
"""
from __future__ import annotations

import threading
import time

from .connection import FRAME_MS, LiveConnection
from .model import GameRun, RunNode, RunNodeKind


class GameRunExecutor:
    def __init__(self, connection: LiveConnection, actions: dict, ref_w: int, ref_h: int, on_log=None):
        self.connection = connection
        self.actions = actions   # dict[str, Action], i.e. project.actions
        self.ref_w = ref_w
        self.ref_h = ref_h
        self._on_log = on_log or (lambda msg: None)
        self._stop = threading.Event()

    def stop(self) -> None:
        """Requests the run wind down: in-flight nodes finish their current
        step (a DELAY sleep or a single action send) but no further node
        fires after that. Idempotent; safe to call from any thread."""
        self._stop.set()

    def run(self, game_run: GameRun) -> None:
        """Runs `game_run` to completion (or until stop()). Blocks the
        calling thread -- callers driving a GUI should call this from a
        worker thread, same pattern as everything else in connection.py."""
        self._stop.clear()
        roots = game_run.roots()
        if not roots:
            self._on_log(f"Run {game_run.name!r}: no root node (every node has an incoming edge) -- nothing to run.")
            return
        self._run_subgraph(game_run, roots)

    # -- internals --------------------------------------------------------

    def _run_subgraph(self, game_run: GameRun, start_ids: list) -> None:
        """Runs every node reachable from `start_ids` to completion (all
        forks joined) and returns. `start_ids` fire immediately and
        concurrently, regardless of their global in-degree -- this is what
        lets a REPEAT's body restart on each iteration without touching
        edges from outside the body."""
        pending = {node_id: len(game_run.incoming(node_id)) for node_id in game_run.nodes}
        lock = threading.Lock()
        done = threading.Event()
        active = [len(start_ids)]

        def fire(node_id: str) -> None:
            node = game_run.nodes[node_id]
            if not self._stop.is_set():
                self._run_node(game_run, node)
            targets = []
            if not self._stop.is_set():
                if node.kind == RunNodeKind.REPEAT:
                    targets = [e.target for e in game_run.outgoing(node_id, via="after")]
                else:
                    targets = [e.target for e in game_run.outgoing(node_id)]
            with lock:
                active[0] -= 1
                to_fire = []
                for target in targets:
                    pending[target] -= 1
                    if pending[target] <= 0:
                        active[0] += 1
                        to_fire.append(target)
                if active[0] == 0:
                    done.set()
            for target in to_fire:
                threading.Thread(target=fire, args=(target,), daemon=True).start()

        for node_id in start_ids:
            threading.Thread(target=fire, args=(node_id,), daemon=True).start()
        done.wait()

    def _run_node(self, game_run: GameRun, node: RunNode) -> None:
        if node.kind == RunNodeKind.ACTION:
            action = self.actions.get(node.action_name)
            if action is None:
                self._on_log(f"node {node.id}: unknown action {node.action_name!r}, skipped")
                return
            skipped = self.connection.run_action(action, self.ref_w, self.ref_h)
            note = f" ({len(skipped)} event(s) skipped)" if skipped else ""
            self._on_log(f"node {node.id}: ran action {node.action_name!r}{note}")
        elif node.kind == RunNodeKind.DELAY:
            self._sleep_frames(node.frames)
        elif node.kind == RunNodeKind.REPEAT:
            body_edges = game_run.outgoing(node.id, via="body")
            if not body_edges:
                self._on_log(f"node {node.id}: repeat has no body connection, skipped")
                return
            body_start = body_edges[0].target
            for i in range(node.times):
                if self._stop.is_set():
                    break
                self._on_log(f"node {node.id}: repeat iteration {i + 1}/{node.times}")
                self._run_subgraph(game_run, [body_start])

    def _sleep_frames(self, frames: int) -> None:
        remaining = frames * FRAME_MS / 1000.0
        step = 0.05
        while remaining > 0 and not self._stop.is_set():
            time.sleep(min(step, remaining))
            remaining -= step
