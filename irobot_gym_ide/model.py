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

    def add_action(self, action: Action) -> None:
        self.actions[action.name] = action

    def remove_action(self, name: str) -> None:
        self.actions.pop(name, None)

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
        return p

    def copy(self) -> "Project":
        return copy.deepcopy(self)
