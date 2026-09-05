"""Executes a GameRun graph against a live connection.

Walks the node DAG: when a node finishes, every one of its outgoing edges
fires concurrently (fork), and a node only starts once every one of its
incoming edges has fired (AND-join) -- plain fork/join, no special-casing,
for every node kind except REPEAT and COMPARE. A REPEAT node instead runs its
"body" edge's target as its own independent fork/join subgraph, to completion,
`times` times in a row (so a fork/join inside the body works exactly like
anywhere else, and a REPEAT nested inside another REPEAT's body just works
too, each with its own fresh join-counters), then fires its single "after"
edge once. A COMPARE node crops the live frame to a stored ImageTemplate's
region, compares it, and fires only its single "match" edge or its single
"no_match" edge depending on the result -- an if/else branch, not a fork.
A FIND_TEMPLATE node instead searches the *whole* live frame for a stored
ImageTemplate and fires only its single "found" edge or its single
"not_found" edge, stashing the best match's (x, y) in `last_found` (keyed
by node id) for the caller to read back once the run finishes or between
node firings -- same if/else-branch spirit as COMPARE, but for "where is
it" instead of "is it here".
See model.py's GameRun docstring for the node/edge vocabulary this executes.

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
    def __init__(self, connection: LiveConnection, actions: dict, ref_w: int, ref_h: int, on_log=None,
                 templates: dict | None = None):
        self.connection = connection
        self.actions = actions   # dict[str, Action], i.e. project.actions
        self.templates = templates or {}   # dict[str, ImageTemplate], i.e. project.templates
        self.ref_w = ref_w
        self.ref_h = ref_h
        self.last_found: dict = {}   # dict[node_id, (x, y)] -- see FIND_TEMPLATE in _run_node
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
            result_via = None
            if not self._stop.is_set():
                result_via = self._run_node(game_run, node)
            targets = []
            if not self._stop.is_set():
                if node.kind == RunNodeKind.REPEAT:
                    targets = [e.target for e in game_run.outgoing(node_id, via="after")]
                elif node.kind in (RunNodeKind.COMPARE, RunNodeKind.FIND_TEMPLATE):
                    targets = [e.target for e in game_run.outgoing(node_id, via=result_via)]
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

    def _run_node(self, game_run: GameRun, node: RunNode) -> str | None:
        """Runs one node's own effect. Returns None for every kind except
        COMPARE (returns "match"/"no_match") and FIND_TEMPLATE (returns
        "found"/"not_found") -- the via role of the one outgoing edge fire()
        should follow (see fire(), above)."""
        if node.kind == RunNodeKind.ACTION:
            action = self.actions.get(node.action_name)
            if action is None:
                self._on_log(f"node {node.id}: unknown action {node.action_name!r}, skipped")
                return None
            skipped = self.connection.run_action(action, self.ref_w, self.ref_h)
            note = f" ({len(skipped)} event(s) skipped)" if skipped else ""
            self._on_log(f"node {node.id}: ran action {node.action_name!r}{note}")
        elif node.kind == RunNodeKind.DELAY:
            self._sleep_frames(node.frames)
        elif node.kind == RunNodeKind.REPEAT:
            body_edges = game_run.outgoing(node.id, via="body")
            if not body_edges:
                self._on_log(f"node {node.id}: repeat has no body connection, skipped")
                return None
            body_start = body_edges[0].target
            for i in range(node.times):
                if self._stop.is_set():
                    break
                self._on_log(f"node {node.id}: repeat iteration {i + 1}/{node.times}")
                self._run_subgraph(game_run, [body_start])
        elif node.kind == RunNodeKind.COMPARE:
            return self._run_compare(node)
        elif node.kind == RunNodeKind.FIND_TEMPLATE:
            return self._run_find_template(node)
        return None

    def _run_compare(self, node: RunNode) -> str:
        """Returns "match" or "no_match" -- never raises, so a missing template
        or a connection with no frame yet just reads as "no_match" (logged),
        same no-surprises spirit as the rest of this module's node handling."""
        template = self.templates.get(node.template_name)
        if template is None:
            self._on_log(f"node {node.id}: unknown template {node.template_name!r}, treated as no_match")
            return "no_match"
        frame = self.connection.latest_frame()
        if frame is None:
            self._on_log(f"node {node.id}: no live frame available yet, treated as no_match")
            return "no_match"
        frame_w, frame_h, frame_arr = frame
        similarity = template.similarity(frame_w, frame_h, frame_arr, self.ref_w, self.ref_h)
        matched = similarity >= template.threshold
        self._on_log(
            f"node {node.id}: compare {template.name!r} similarity={similarity:.3f} "
            f"(threshold {template.threshold:.2f}) -> {'match' if matched else 'no_match'}")
        return "match" if matched else "no_match"

    def _run_find_template(self, node: RunNode) -> str:
        """Returns "found" or "not_found" -- never raises, same no-surprises
        spirit as _run_compare. On a find, stashes the match's (x, y) --
        already in the project's reference resolution, see ImageTemplate.find
        -- in `self.last_found[node.id]` so the caller can read back *where*
        the template turned up, not just whether it did."""
        template = self.templates.get(node.template_name)
        if template is None:
            self._on_log(f"node {node.id}: unknown template {node.template_name!r}, treated as not_found")
            return "not_found"
        frame = self.connection.latest_frame()
        if frame is None:
            self._on_log(f"node {node.id}: no live frame available yet, treated as not_found")
            return "not_found"
        frame_w, frame_h, frame_arr = frame
        result = template.find(frame_w, frame_h, frame_arr, self.ref_w, self.ref_h)
        if result is None:
            self._on_log(f"node {node.id}: find_template {template.name!r} region does not fit the live frame, "
                         f"treated as not_found")
            return "not_found"
        x, y, similarity = result
        found = similarity >= template.threshold
        self._on_log(
            f"node {node.id}: find_template {template.name!r} best match ({x}, {y}) similarity={similarity:.3f} "
            f"(threshold {template.threshold:.2f}) -> {'found' if found else 'not_found'}")
        if found:
            self.last_found[node.id] = (x, y)
        return "found" if found else "not_found"

    def _sleep_frames(self, frames: int) -> None:
        remaining = frames * FRAME_MS * self.connection.time_scale / 1000.0
        step = 0.05
        while remaining > 0 and not self._stop.is_set():
            time.sleep(min(step, remaining))
            remaining -= step
