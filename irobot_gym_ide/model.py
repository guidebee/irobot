"""Headless data model for irobot Gym IDE projects.

No Qt import here on purpose (see package docstring) -- this module is the
schema that both the GUI and, eventually, tools/irobot_gym/env.py load.

Vocabulary, deliberately minimal per the design doc's "start with single
events, build actions as combinations" scoping:

  PrimitiveEvent -- one atomic wire-level unit: tap a point, press a point
      down (and hold it), release a held pointer, move a held pointer, send
      a keycode, or wait N frames before the next event in the sequence.
      Each maps directly onto a control_msg.hpp message shape (or, for
      WAIT, onto no wire message at all).

  Action -- a named, ordered list of PrimitiveEvents. A tap action is one
      TAP event. A "hold left" action is a single PRESS event (the pointer
      stays down after the action finishes -- the caller decides when to
      issue the matching "release left" action). A composed action like
      "hold left, then after 10 frames also tap jump" is just a longer
      event list -- no special-case gesture type needed.

  Project -- a named game: connection defaults, the reference resolution
      calibration was done against (see connection.py), and its actions.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EventKind(str, Enum):
    TAP = "tap"          # DOWN immediately followed by UP -- a single quick touch
    PRESS = "press"       # DOWN only; pointer stays held until a matching RELEASE
    RELEASE = "release"   # UP for a pointer a prior PRESS left held
    MOVE = "move"          # MOVE a currently-held pointer to a new (x, y)
    KEY = "key"            # keycode DOWN immediately followed by UP
    WAIT = "wait"           # no wire message -- just a delay (in frames) before the next event


@dataclass
class PrimitiveEvent:
    kind: EventKind
    pointer_id: int = 0
    x: Optional[int] = None
    y: Optional[int] = None
    keycode: Optional[int] = None
    key_name: Optional[str] = None   # human label; resolved to `keycode` via agent_client.android_keycode
    frames: int = 0                  # WAIT duration in frames; ignored by other kinds

    def to_dict(self) -> dict:
        d = {"kind": self.kind.value}
        if self.pointer_id:
            d["pointer_id"] = self.pointer_id
        if self.x is not None:
            d["x"] = self.x
        if self.y is not None:
            d["y"] = self.y
        if self.keycode is not None:
            d["keycode"] = self.keycode
        if self.key_name:
            d["key_name"] = self.key_name
        if self.frames:
            d["frames"] = self.frames
        return d

    @staticmethod
    def from_dict(d: dict) -> "PrimitiveEvent":
        d = dict(d)
        d["kind"] = EventKind(d["kind"])
        return PrimitiveEvent(**d)


_NEEDS_POSITION = {EventKind.TAP, EventKind.PRESS, EventKind.RELEASE, EventKind.MOVE}
_NEEDS_KEY = {EventKind.KEY}


@dataclass
class Action:
    name: str
    events: list = field(default_factory=list)   # list[PrimitiveEvent]
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "events": [e.to_dict() for e in self.events],
        }

    @staticmethod
    def from_dict(d: dict) -> "Action":
        return Action(
            name=d["name"],
            description=d.get("description", ""),
            events=[PrimitiveEvent.from_dict(e) for e in d.get("events", [])],
        )

    def validate(self) -> list:
        """Static authoring-time checks that don't require knowing about any
        *other* action in the project. Returns a list of human-readable
        warnings, empty if the action looks internally consistent.

        Deliberately does NOT flag a RELEASE/MOVE with no PRESS earlier in
        this same action -- that's the idiomatic shape of a split
        start/stop action pair (e.g. `move_left_start` PRESSes pointer 0,
        `move_left_stop` is a lone RELEASE on pointer 0 -- see
        examples/mario_platformer.yaml), which is a normal, encouraged
        pattern for hold-based controls, not a mistake. A pointer's state at
        the *start* of one action is simply unknown without looking at every
        other action, so this method only tracks state it can be sure of
        from this action's own events. The one thing it CAN safely flag
        locally is a double PRESS on the same pointer with no RELEASE
        between them -- that is a contradiction regardless of what any other
        action does. The project-wide check that DOES look across actions
        (an orphaned RELEASE with no PRESS anywhere in the project to pair
        with) is `orphan_releases()`, below."""
        warnings = []
        held = set()
        for i, ev in enumerate(self.events):
            if ev.kind in _NEEDS_POSITION and (ev.x is None or ev.y is None) and ev.kind != EventKind.RELEASE:
                warnings.append(f"event {i} ({ev.kind.value}) has no (x, y)")
            if ev.kind in _NEEDS_KEY and ev.keycode is None and not ev.key_name:
                warnings.append(f"event {i} (key) has no keycode/key_name")
            if ev.kind == EventKind.PRESS:
                if ev.pointer_id in held:
                    warnings.append(f"event {i}: PRESS on pointer {ev.pointer_id} which is already held (in this action)")
                held.add(ev.pointer_id)
            elif ev.kind == EventKind.RELEASE:
                held.discard(ev.pointer_id)
        return warnings


def orphan_releases(actions: dict) -> list:
    """Project-wide check: a RELEASE on a pointer_id that no action in the
    whole project ever PRESSes is very likely a typo'd pointer_id or a
    leftover event, since there is then no action that could have left that
    pointer held. Returns a list of (action_name, pointer_id) pairs."""
    pressed_pointers = set()
    for action in actions.values():
        for ev in action.events:
            if ev.kind == EventKind.PRESS:
                pressed_pointers.add(ev.pointer_id)

    orphans = []
    for action in actions.values():
        held = set()
        for ev in action.events:
            if ev.kind == EventKind.PRESS:
                held.add(ev.pointer_id)
            elif ev.kind == EventKind.RELEASE:
                if ev.pointer_id in held:
                    held.discard(ev.pointer_id)
                elif ev.pointer_id not in pressed_pointers:
                    orphans.append((action.name, ev.pointer_id))
    return orphans


def conflicting_pointer_actions(actions: dict) -> list:
    """Cross-action check: two actions that PRESS the same pointer_id and never
    RELEASE it are only safe if the integrator intends them as mutually exclusive
    "hold" actions for one physical thumb (e.g. `left`/`right` sharing pointer 0,
    per docs/opengym_implementation_plan.md §7.4's Tier 1.5). This just reports
    the grouping so the IDE can surface it -- it is not necessarily an error."""
    groups: dict = {}
    for action in actions.values():
        held_at_end = set()
        for ev in action.events:
            if ev.kind == EventKind.PRESS:
                held_at_end.add(ev.pointer_id)
            elif ev.kind == EventKind.RELEASE:
                held_at_end.discard(ev.pointer_id)
        for pid in held_at_end:
            groups.setdefault(pid, []).append(action.name)
    return [(pid, names) for pid, names in groups.items() if len(names) > 1]


class RunNodeKind(str, Enum):
    ACTION = "action"   # runs one already-defined Action (by name) against the device
    DELAY = "delay"      # waits `frames` frames, no wire message -- same unit as PrimitiveEvent.WAIT
    REPEAT = "repeat"     # runs its "body"-edge target's subgraph to completion `times` times,
                          # then continues once through its "after"-edge target, if any


@dataclass
class RunNode:
    id: str
    kind: RunNodeKind
    x: float = 0.0    # canvas position -- authoring layout only, has no effect on execution
    y: float = 0.0
    action_name: str = ""   # ACTION only
    frames: int = 0          # DELAY only
    times: int = 1            # REPEAT only

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind.value, "x": self.x, "y": self.y}
        if self.kind == RunNodeKind.ACTION:
            d["action_name"] = self.action_name
        elif self.kind == RunNodeKind.DELAY:
            d["frames"] = self.frames
        elif self.kind == RunNodeKind.REPEAT:
            d["times"] = self.times
        return d

    @staticmethod
    def from_dict(d: dict) -> "RunNode":
        return RunNode(
            id=d["id"], kind=RunNodeKind(d["kind"]), x=d.get("x", 0.0), y=d.get("y", 0.0),
            action_name=d.get("action_name", ""), frames=d.get("frames", 0), times=d.get("times", 1),
        )


@dataclass
class RunEdge:
    id: str
    source: str   # RunNode.id
    target: str   # RunNode.id
    # "out" for a plain fork edge (any non-REPEAT source, or a REPEAT source that hasn't been
    # assigned a role yet). Meaningful only when `source` is a REPEAT node: "body" marks the one
    # edge that starts the loop body, "after" marks the one edge that runs once after all
    # iterations finish. See GameRun docstring for why REPEAT needs this and no other node does.
    via: str = "out"

    def to_dict(self) -> dict:
        d = {"id": self.id, "source": self.source, "target": self.target}
        if self.via != "out":
            d["via"] = self.via
        return d

    @staticmethod
    def from_dict(d: dict) -> "RunEdge":
        return RunEdge(id=d["id"], source=d["source"], target=d["target"], via=d.get("via", "out"))


@dataclass
class GameRun:
    """A drag-and-drop node graph over already-defined Actions, run_engine.py's
    GameRunExecutor is the runtime for this: a node with more than one outgoing
    edge forks (all targets start concurrently); a node with more than one
    incoming edge joins (it waits until every incoming edge's source has
    finished before it starts). REPEAT is the one node kind that isn't just
    fork/join: rather than firing all its outgoing edges once, it repeats its
    "body" edge's target subgraph to completion `times` times, then fires its
    single "after" edge once (see RunEdge.via). There's no explicit
    start/end node kind -- a node with no incoming edges is a root and starts
    immediately (multiple roots start in parallel); a node with no outgoing
    edges just ends its branch.
    """
    name: str
    nodes: dict = field(default_factory=dict)   # dict[str, RunNode]
    edges: list = field(default_factory=list)    # list[RunEdge]

    def add_node(self, node: RunNode) -> None:
        self.nodes[node.id] = node

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges if e.source != node_id and e.target != node_id]

    def add_edge(self, edge: RunEdge) -> None:
        self.edges.append(edge)

    def remove_edge(self, edge_id: str) -> None:
        self.edges = [e for e in self.edges if e.id != edge_id]

    def outgoing(self, node_id: str, via: Optional[str] = None) -> list:
        return [e for e in self.edges if e.source == node_id and (via is None or e.via == via)]

    def incoming(self, node_id: str) -> list:
        return [e for e in self.edges if e.target == node_id]

    def roots(self) -> list:
        """Node ids with no incoming edge -- see class docstring."""
        return [node_id for node_id in self.nodes if not self.incoming(node_id)]

    def validate(self, project_actions: dict) -> list:
        """Static authoring-time checks. Returns human-readable warnings, empty
        if the graph looks internally consistent. Does not catch every
        possible malformed graph (e.g. a node shared between a repeat body and
        the outer graph) -- see run_engine.py's module docstring."""
        warnings = []
        for edge in self.edges:
            if edge.source not in self.nodes:
                warnings.append(f"edge {edge.id}: unknown source node {edge.source!r}")
            if edge.target not in self.nodes:
                warnings.append(f"edge {edge.id}: unknown target node {edge.target!r}")
        for node in self.nodes.values():
            if node.kind == RunNodeKind.ACTION and node.action_name not in project_actions:
                warnings.append(f"node {node.id}: unknown action {node.action_name!r}")
            if node.kind == RunNodeKind.REPEAT:
                if node.times < 1:
                    warnings.append(f"node {node.id}: repeat times must be >= 1")
                if len(self.outgoing(node.id, via="body")) > 1:
                    warnings.append(f"node {node.id}: repeat has more than one body connection")
                if len(self.outgoing(node.id, via="after")) > 1:
                    warnings.append(f"node {node.id}: repeat has more than one after-loop connection")
            else:
                for e in self.outgoing(node.id):
                    if e.via != "out":
                        warnings.append(f"edge {e.id}: via={e.via!r} is only valid from a repeat node")
        return warnings

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
        }

    @staticmethod
    def from_dict(d: dict) -> "GameRun":
        run = GameRun(name=d["name"])
        for n in d.get("nodes", []):
            run.add_node(RunNode.from_dict(n))
        for e in d.get("edges", []):
            run.add_edge(RunEdge.from_dict(e))
        return run


@dataclass
class Project:
    name: str
    package: str = ""
    activity: str = ""
    serial: str = ""
    host: str = "127.0.0.1"
    port: int = 27183
    reference_width: int = 0
    reference_height: int = 0
    actions: dict = field(default_factory=dict)   # dict[str, Action]
    runs: dict = field(default_factory=dict)        # dict[str, GameRun]

    def add_action(self, action: Action) -> None:
        self.actions[action.name] = action

    def remove_action(self, name: str) -> None:
        self.actions.pop(name, None)

    def add_run(self, run: GameRun) -> None:
        self.runs[run.name] = run

    def remove_run(self, name: str) -> None:
        self.runs.pop(name, None)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "name": self.name,
            "package": self.package,
            "activity": self.activity,
            "serial": self.serial,
            "host": self.host,
            "port": self.port,
            "reference_resolution": {"width": self.reference_width, "height": self.reference_height},
            "actions": [a.to_dict() for a in self.actions.values()],
            "runs": [r.to_dict() for r in self.runs.values()],
        }

    @staticmethod
    def from_dict(d: dict) -> "Project":
        res = d.get("reference_resolution", {})
        p = Project(
            name=d["name"],
            package=d.get("package", ""),
            activity=d.get("activity", ""),
            serial=d.get("serial", ""),
            host=d.get("host", "127.0.0.1"),
            port=d.get("port", 27183),
            reference_width=res.get("width", 0),
            reference_height=res.get("height", 0),
        )
        for a in d.get("actions", []):
            p.add_action(Action.from_dict(a))
        for r in d.get("runs", []):
            p.add_run(GameRun.from_dict(r))
        return p

    def copy(self) -> "Project":
        return copy.deepcopy(self)
