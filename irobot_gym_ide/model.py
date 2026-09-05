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

import base64
import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


def frames_between(events: list, lo: int, hi: int) -> int:
    """Sums the `frames` of every WAIT event in events[lo:hi) -- the real recorded gap, in
    frames, spanned by that slice. Used by session_replay.py to compute how long to wait
    before firing the next classified segment's action (so replay timing between segments
    reflects how the session actually played out rather than firing actions back-to-back),
    and by hud_classifier.build_game_run to give a synthesized GameRun's DELAY nodes that
    same real gap."""
    return sum(e.frames for e in events[lo:hi] if e.kind == EventKind.WAIT)


def _events_match_distance(a_events: list, b_events: list, position_tolerance_px: int) -> Optional[float]:
    """None if two PrimitiveEvent sequences don't look like recordings of the same physical
    gesture at all (different non-WAIT event kinds/order/pointer_id/key, or any
    corresponding position more than `position_tolerance_px` apart); otherwise the summed
    pixel distance between their corresponding positions -- smaller means a closer match.
    WAIT durations are ignored entirely (filtered out of both sequences before comparing):
    two recordings of "the same" hold or drag will never have pixel/frame-identical timing,
    and that difference alone shouldn't read as "a different gesture."

    Deliberately a plain, explainable heuristic (position tolerance + kind/pointer/key
    equality, then nearest-distance ranking) rather than a trained/statistical model -- see
    hud_classifier.py's module docstring for why: touch events already carry exact discrete
    kinds and coordinates, so there's no genuine ambiguity here for a learned model to
    resolve, just "close enough" positions to tolerate real finger-placement jitter between
    takes, and "which of several close-enough candidates is closest" once more than one
    qualifies."""
    a = [e for e in a_events if e.kind != EventKind.WAIT]
    b = [e for e in b_events if e.kind != EventKind.WAIT]
    if len(a) != len(b):
        return None
    total = 0.0
    for ea, eb in zip(a, b):
        if ea.kind != eb.kind or ea.pointer_id != eb.pointer_id:
            return None
        if ea.kind == EventKind.KEY:
            if (ea.keycode, ea.key_name) != (eb.keycode, eb.key_name):
                return None
            continue
        if ea.x is None or ea.y is None or eb.x is None or eb.y is None:
            if (ea.x, ea.y) != (eb.x, eb.y):
                return None
            continue
        dx, dy = abs(ea.x - eb.x), abs(ea.y - eb.y)
        if dx > position_tolerance_px or dy > position_tolerance_px:
            return None
        total += dx + dy
    return total


def events_look_alike(a_events: list, b_events: list, position_tolerance_px: int = 30) -> bool:
    """True if two PrimitiveEvent sequences look like recordings of the same physical
    gesture -- see _events_match_distance for the exact rule."""
    return _events_match_distance(a_events, b_events, position_tolerance_px) is not None


def find_matching_action(events: list, actions: dict, position_tolerance_px: int = 30,
                          on_ambiguous=None) -> Optional[str]:
    """The name of the action in `actions` (dict[str, Action]) whose own events look MOST
    alike `events` -- the smallest _events_match_distance among every candidate within
    `position_tolerance_px` -- or None if none qualify. Picking the nearest candidate
    instead of just the first one in dict order matters precisely because the action
    library keeps growing as the project's classify/propose loop runs (see
    ACTION_CLASSIFICATION_DESIGN.md G3): more entries means a higher chance more than one is
    within tolerance, and an arbitrary first-match would get *less* reliable exactly as the
    library "improves." `on_ambiguous`, if given, is called with the sorted list of every
    candidate name that qualified (nearest first) whenever more than one did, so a caller
    can log/flag that the match wasn't unique. Used both to flag a newly proposed action as
    a likely duplicate of an existing one (see hud_classifier.propose_actions) and to let a
    fresh recording's own raw gesture be recognized directly against the project's growing
    action library, not just against HudRegions (see hud_classifier.classify_session)."""
    candidates = []
    for name, action in actions.items():
        distance = _events_match_distance(events, action.events, position_tolerance_px)
        if distance is not None:
            candidates.append((distance, name))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    if len(candidates) > 1 and on_ambiguous is not None:
        on_ambiguous([name for _distance, name in candidates])
    return candidates[0][1]


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


def classified_pointer_conflicts(segments: list, actions: dict) -> list:
    """Simulates the held-pointer state a live LiveConnection tracks (connection.py's
    `_held_pointers`) while replaying `segments` (a GameplaySession's, in start_index order)
    -- not just a static per-action check like conflicting_pointer_actions, an actual
    *sequence* simulation, since the bug this catches only shows up when a hold from one
    segment is still open when a later segment's action touches the same pointer_id.

    Concretely: connection.py's send_primitive silently *skips* a PRESS on an
    already-held pointer (logged as a skipped event, easy to miss), but a RELEASE on that
    pointer still goes through -- so a plain tap-style action sharing pointer_id 0 with an
    unrelated hold doesn't just fail to press its own touch, its own RELEASE event actively
    ends the unrelated hold early. This is exactly what made "Replay Classified" replay
    wrong for a hold with an interleaved, differently-authored tap (see
    ACTION_CLASSIFICATION_DESIGN.md): a HudRegion pointing at a hold action's pointer, with
    another action likely to run concurrently (per an unmatched overlapping cluster) sharing
    that same pointer_id.

    Returns human-readable warnings, one per conflicting segment. Pure function; reasons
    only about PRESS/RELEASE pointer_ids in `segments`' own referenced actions' events, not
    positions or timing."""
    warnings = []
    held: dict = {}   # pointer_id -> description of the segment currently holding it
    for seg in sorted(segments, key=lambda s: s.start_index):
        action = actions.get(seg.action_name)
        if action is None:
            continue
        desc = f"{seg.label or seg.action_name!r} ({seg.action_name!r})"
        for event in action.events:
            if event.kind == EventKind.PRESS:
                holder = held.get(event.pointer_id)
                if holder is not None:
                    warnings.append(
                        f"segment {desc} presses pointer {event.pointer_id}, still held by segment "
                        f"{holder} -- give one of these actions a different pointer_id, or the hold "
                        f"will end early / the press will be silently skipped during replay.")
                held[event.pointer_id] = desc
            elif event.kind == EventKind.RELEASE:
                held.pop(event.pointer_id, None)
    return warnings


def scale_point(x: int, y: int, ref_w: int, ref_h: int, target_w: int, target_h: int) -> tuple:
    """Scales a point given in `ref_w`x`ref_h` space into `target_w`x`target_h` space --
    same per-axis linear scaling `_scale_rect` uses for a rectangle's origin, extracted as
    its own function since connection.py needs to scale a bare (x, y) touch coordinate (not
    a rectangle) when resolving a recorded event against a live device whose real negotiated
    resolution differs from the project's reference resolution -- see
    LiveConnection.send_primitive's docstring for why this is what makes a shared project
    portable across devices with different screen resolutions, instead of every event being
    silently dropped (irobot_server requires an exact screen-size match) or landing in the
    wrong place. Falls back to an identity mapping when either reference size is zero, same
    as `_scale_rect`."""
    if not ref_w or not ref_h:
        return x, y
    return round(x / ref_w * target_w), round(y / ref_h * target_h)


def _scale_rect(x: int, y: int, w: int, h: int, ref_w: int, ref_h: int, target_w: int, target_h: int):
    """Scales a rectangle given in `ref_w`x`ref_h` space into `target_w`x`target_h`
    space -- same ratio scaling as MainWindow._reference_to_frame/_frame_to_reference,
    extracted here so ImageTemplate can do it from run_engine.py too (which has no Qt
    import and must not gain one -- see this module's and run_engine.py's docstrings).
    Falls back to an identity mapping when no reference resolution is set, same as the
    GUI helpers do."""
    if not ref_w or not ref_h:
        return x, y, w, h
    sx, sy = target_w / ref_w, target_h / ref_h
    nx, ny = scale_point(x, y, ref_w, ref_h, target_w, target_h)
    return nx, ny, max(1, round(w * sx)), max(1, round(h * sy))


def _resize_nearest(arr, new_w: int, new_h: int):
    """Nearest-neighbor resize of a 2D numpy array. Needed because the live video
    frame's own resolution (a downscaled mirror, see connection.py) can differ from
    whatever it was when a template was captured -- e.g. after a resolution/orientation
    change -- so the region cropped out of a fresh frame at compare time isn't
    guaranteed to already be pixel-for-pixel the same size as the stored template.
    Deliberately not a real interpolation library (no such dependency exists in this
    package, see requirements.txt) -- this is a same-region approximate match for
    scripting game-run conditions, not pixel-perfect comparison."""
    h, w = arr.shape
    if (w, h) == (new_w, new_h):
        return arr
    import numpy as np
    ys = (np.arange(new_h) * h / new_h).astype(int).clip(0, h - 1)
    xs = (np.arange(new_w) * w / new_w).astype(int).clip(0, w - 1)
    return arr[ys][:, xs]


@dataclass
class ImageTemplate:
    """A named reference image captured from a region of the live frame, for a
    Compare run-node to test "does the screen currently look like this" (e.g. a
    game-over banner, a full health bar) as a condition in a GameRun graph.

    `x`/`y`/`width`/`height` are in the project's reference resolution, same
    convention as PrimitiveEvent's (x, y) -- resolution-independent, so the region
    still lines up with the right part of the screen even if the live (downscaled)
    frame's own pixel size differs between capture and comparison. `pixels_b64` is
    the captured region's own grayscale pixels (`image_w`x`image_h`, whatever size
    that crop came out to at capture time), base64-encoded raw bytes -- no PNG/image
    codec dependency needed since the source frames are already raw grayscale numpy
    arrays (see connection.py's latest_frame)."""
    name: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    threshold: float = 0.9   # similarity in [0, 1] at/above which run_engine.py calls it a match
    image_w: int = 0
    image_h: int = 0
    pixels_b64: str = ""

    @staticmethod
    def capture(name: str, x: int, y: int, width: int, height: int, frame_w: int, frame_h: int, frame,
                ref_res_w: int, ref_res_h: int, threshold: float = 0.9) -> "ImageTemplate":
        """Builds a template named `name` covering the rectangle (x, y, width,
        height), given in the project's reference resolution (ref_res_w, ref_res_h)
        -- same convention as PrimitiveEvent.x/y, and same reference/frame split as
        MainWindow's _frame_to_reference/_reference_to_frame -- by cropping `frame`
        (a grayscale numpy array, shape (frame_h, frame_w), what connection.py's
        latest_frame() returns) at that rectangle scaled into the frame's own size."""
        fx, fy, fw, fh = _scale_rect(x, y, width, height, ref_res_w, ref_res_h, frame_w, frame_h)
        fx, fy = max(0, fx), max(0, fy)
        fx2, fy2 = min(frame_w, fx + fw), min(frame_h, fy + fh)
        crop = frame[fy:fy2, fx:fx2]
        return ImageTemplate(
            name=name, x=x, y=y, width=width, height=height, threshold=threshold,
            image_w=int(crop.shape[1]), image_h=int(crop.shape[0]),
            pixels_b64=base64.b64encode(crop.tobytes()).decode("ascii"),
        )

    def similarity(self, frame_w: int, frame_h: int, frame, ref_w: int, ref_h: int) -> float:
        """Compares this template's stored pixels against the matching region of a
        fresh live `frame`, scaling the stored (reference-space) region into that
        frame's own size the same way `capture` scaled it out in the first place.
        Returns a value in [0, 1] -- 1.0 is a pixel-identical match, computed as
        1 - mean absolute grayscale difference / 255. Returns 0.0 if the template
        has no captured pixels yet, or the scaled region falls entirely off-frame."""
        if not self.pixels_b64 or not self.image_w or not self.image_h:
            return 0.0
        import numpy as np
        template_pixels = np.frombuffer(base64.b64decode(self.pixels_b64), dtype=np.uint8)
        template_pixels = template_pixels.reshape((self.image_h, self.image_w))
        fx, fy, fw, fh = _scale_rect(self.x, self.y, self.width, self.height, ref_w, ref_h, frame_w, frame_h)
        fx, fy = max(0, fx), max(0, fy)
        fx2, fy2 = min(frame_w, fx + fw), min(frame_h, fy + fh)
        crop = frame[fy:fy2, fx:fx2]
        if crop.size == 0:
            return 0.0
        crop = _resize_nearest(crop, self.image_w, self.image_h)
        diff = np.abs(crop.astype(np.int16) - template_pixels.astype(np.int16))
        return 1.0 - float(diff.mean()) / 255.0

    def matches(self, frame_w: int, frame_h: int, frame, ref_w: int, ref_h: int) -> bool:
        return self.similarity(frame_w, frame_h, frame, ref_w, ref_h) >= self.threshold

    def find(self, frame_w: int, frame_h: int, frame, ref_w: int, ref_h: int,
              stride: int = 4) -> Optional[tuple]:
        """Slides this template's own captured region size across the *whole*
        live `frame` looking for the best match, unlike `similarity`/`matches`
        which only ever look at this template's own fixed (x, y) region --
        this is what a Find Template run-node needs to locate something that
        may have moved (e.g. a coin, an enemy) rather than test a fixed HUD
        region. Returns (x, y, similarity) with (x, y) the best-matching
        top-left corner converted into the project's reference resolution --
        same convention as PrimitiveEvent.x/y -- or None if the template has
        no captured pixels or its region no longer fits inside the frame.

        Two passes trade search speed for precision: a coarse pass checks
        positions `stride` pixels apart (the frame's final row/column is
        always included so the search still reaches the far edge), then a
        single-pixel refinement pass re-scans just the neighborhood around
        the coarse winner -- without it, a target that doesn't happen to
        land on the coarse grid would score artificially low (its true
        position is between two checked points) and could read as a false
        not_found even sitting right on top of an exact match."""
        if not self.pixels_b64 or not self.image_w or not self.image_h:
            return None
        import numpy as np
        template_pixels = np.frombuffer(base64.b64decode(self.pixels_b64), dtype=np.uint8)
        template_pixels = template_pixels.reshape((self.image_h, self.image_w))
        _, _, fw, fh = _scale_rect(self.x, self.y, self.width, self.height, ref_w, ref_h, frame_w, frame_h)
        if fw > frame_w or fh > frame_h or fw <= 0 or fh <= 0:
            return None
        tmpl = _resize_nearest(template_pixels, fw, fh)
        best_similarity = None
        best_fx, best_fy = 0, 0

        def scan(xs, ys) -> None:
            nonlocal best_similarity, best_fx, best_fy
            for fy in ys:
                for fx in xs:
                    crop = frame[fy:fy + fh, fx:fx + fw]
                    diff = np.abs(crop.astype(np.int16) - tmpl.astype(np.int16))
                    similarity = 1.0 - float(diff.mean()) / 255.0
                    if best_similarity is None or similarity > best_similarity:
                        best_similarity = similarity
                        best_fx, best_fy = fx, fy

        def steps(limit: int, step: int) -> list:
            values = list(range(0, limit + 1, step))
            if values[-1] != limit:
                values.append(limit)
            return values

        stride = max(1, stride)
        scan(steps(frame_w - fw, stride), steps(frame_h - fh, stride))
        if stride > 1:
            x_lo, x_hi = max(0, best_fx - stride), min(frame_w - fw, best_fx + stride)
            y_lo, y_hi = max(0, best_fy - stride), min(frame_h - fh, best_fy + stride)
            scan(range(x_lo, x_hi + 1), range(y_lo, y_hi + 1))
        rx, ry, _, _ = _scale_rect(best_fx, best_fy, fw, fh, frame_w, frame_h, ref_w, ref_h)
        return (rx, ry, best_similarity)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "x": self.x, "y": self.y, "width": self.width, "height": self.height,
            "threshold": self.threshold, "image_w": self.image_w, "image_h": self.image_h,
            "pixels_b64": self.pixels_b64,
        }

    @staticmethod
    def from_dict(d: dict) -> "ImageTemplate":
        return ImageTemplate(
            name=d["name"], x=d.get("x", 0), y=d.get("y", 0),
            width=d.get("width", 0), height=d.get("height", 0),
            threshold=d.get("threshold", 0.9),
            image_w=d.get("image_w", 0), image_h=d.get("image_h", 0),
            pixels_b64=d.get("pixels_b64", ""),
        )


@dataclass
class HudRegion:
    """A fixed-position rectangle over a game's HUD -- a joystick, a jump
    button, an attack button -- named and paired with the Action(s) a gesture
    landing inside it represents. Unlike ImageTemplate (which compares
    pixels to test whether something currently *looks* a certain way), a
    HudRegion is purely spatial: it classifies WHERE a gesture started, not
    what the screen looks like, so it needs no captured pixels and no live
    frame.

    `x`/`y`/`width`/`height` are in the project's reference resolution --
    same convention ImageTemplate and PrimitiveEvent.x/y already use -- which
    is also exactly the coordinate space a recorded gesture's own (x, y) is
    already stored in (see device_recorder.gesture_to_events). So, unlike
    ImageTemplate's ImageTemplate._scale_rect dance, classifying a gesture
    against a HudRegion needs no frame-size scaling at all: a straight point-
    in-rectangle test against the region's own reference-resolution
    coordinates already lines up.

    `release_action_name`, if set, marks this region as a HOLD control (a
    movement d-pad button, not a one-shot tap button like jump/attack) --
    mirroring Android's real touchscreen model, where a held button is one
    DOWN, silence while held, and one UP (see model.py's module docstring
    and the *_start/*_stop action pairs in examples/mario_platformer.yaml).
    For a hold region, `action_name` names the action fired when the finger
    lands (the "start" half, e.g. "right_start") and `release_action_name`
    names the action fired when it lifts (the "stop" half, e.g.
    "right_stop") -- hud_classifier.py emits two bookend SessionSegments for
    such a region instead of one segment spanning the whole gesture, so
    "Replay Classified" reproduces the real held duration rather than
    running a fixed-length canned action. Left "" (the default), a region is
    a plain one-shot control and `action_name` alone names the single action
    for its whole gesture, exactly as before this field existed.

    See hud_classifier.py for how a project's HudRegions turn a
    GameplaySession's raw gesture stream into SessionSegments."""
    name: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    action_name: str = ""
    release_action_name: str = ""

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def is_hold(self) -> bool:
        return bool(self.release_action_name)

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def to_dict(self) -> dict:
        return {
            "name": self.name, "x": self.x, "y": self.y, "width": self.width, "height": self.height,
            "action_name": self.action_name, "release_action_name": self.release_action_name,
        }

    @staticmethod
    def from_dict(d: dict) -> "HudRegion":
        return HudRegion(
            name=d["name"], x=d.get("x", 0), y=d.get("y", 0),
            width=d.get("width", 0), height=d.get("height", 0),
            action_name=d.get("action_name", ""),
            release_action_name=d.get("release_action_name", ""),
        )


@dataclass
class HudRegionCombo:
    """Names the Action that two or more HudRegions touched *concurrently*
    represent -- e.g. holding "right_button" while tapping "jump_button"
    means "right_jump", not two independent inputs. `region_names` is the
    exact set of HudRegion names (by HudRegion.name) that must all be
    touched at overlapping times for hud_classifier.classify_session to
    treat it as this combo rather than emitting each region's own action
    separately; order doesn't matter and is not preserved (see
    hud_classifier.py's set-based matching).

    Deliberately opt-in and explicit, not auto-detected: two regions
    overlapping in a recorded session is common and often *not* meaningful
    (e.g. a drag that incidentally crosses a second region on its way
    somewhere else), so classify_session only merges concurrent regions into
    one combo segment when their exact set matches a HudRegionCombo an
    author defined -- otherwise it falls back to classifying each region's
    gesture separately, same as if no combo existed at all."""
    name: str
    region_names: list = field(default_factory=list)
    action_name: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "region_names": list(self.region_names), "action_name": self.action_name}

    @staticmethod
    def from_dict(d: dict) -> "HudRegionCombo":
        return HudRegionCombo(
            name=d["name"], region_names=list(d.get("region_names", [])), action_name=d.get("action_name", ""),
        )


@dataclass
class SessionSegment:
    """One classified span within a GameplaySession's raw `events` list --
    [start_index, end_index) -- labeled as the name of an Action it
    represents (an existing project action, or one a classifier is
    proposing be added). Never produced by recording itself; this is the
    hook contract a later segmentation step (human, heuristic, or AI -- see
    GAME_RUN_AI_ASSIST_DESIGN.md §3 for the human-review precedent this
    should follow) writes into a saved session for the "Replay Classified"
    path to consume."""
    start_index: int
    end_index: int
    action_name: str
    label: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict:
        d = {"start_index": self.start_index, "end_index": self.end_index, "action_name": self.action_name}
        if self.label:
            d["label"] = self.label
        if self.confidence != 1.0:
            d["confidence"] = self.confidence
        return d

    @staticmethod
    def from_dict(d: dict) -> "SessionSegment":
        return SessionSegment(
            start_index=d["start_index"], end_index=d["end_index"], action_name=d["action_name"],
            label=d.get("label", ""), confidence=d.get("confidence", 1.0),
        )


@dataclass
class GameplaySession:
    """A recorded gameplay session: a flat, chronological raw PrimitiveEvent
    stream captured over an entire playthrough (many gestures, not collapsed
    into one Action the way "Record from Device" does today -- see
    device_recorder.merge_gestures_into_events, which is exactly what builds
    this `events` list). Saved separately from project.yaml (see io.py) since
    it can be large and isn't part of the ActionMap-shaped authoring schema
    env.py will load.

    `segments` starts empty -- a session is "raw only" until something fills
    it in (see SessionSegment). Replay has two independent modes over the
    same saved file: "Replay Raw" just sends `events` in order (identical to
    running an Action built from them); "Replay Classified" walks `segments`
    in order, running each one's named Action with the real recorded gap
    timing between them (see session_replay.py's SessionPlayer for both)."""
    name: str
    created_at: str = ""
    source: str = "device"
    reference_width: int = 0
    reference_height: int = 0
    events: list = field(default_factory=list)     # list[PrimitiveEvent]
    segments: list = field(default_factory=list)     # list[SessionSegment]
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "name": self.name,
            "created_at": self.created_at,
            "source": self.source,
            "reference_resolution": {"width": self.reference_width, "height": self.reference_height},
            "events": [e.to_dict() for e in self.events],
            "segments": [s.to_dict() for s in self.segments],
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(d: dict) -> "GameplaySession":
        res = d.get("reference_resolution", {})
        return GameplaySession(
            name=d["name"],
            created_at=d.get("created_at", ""),
            source=d.get("source", "device"),
            reference_width=res.get("width", 0),
            reference_height=res.get("height", 0),
            events=[PrimitiveEvent.from_dict(e) for e in d.get("events", [])],
            segments=[SessionSegment.from_dict(s) for s in d.get("segments", [])],
            notes=d.get("notes", ""),
        )

    def validate(self, project_actions: dict) -> list:
        """Static authoring-time checks over `segments`, same "return
        human-readable warnings, never raise" convention as Action.validate/
        GameRun.validate. Segments are expected in ascending, non-overlapping
        order (each one's action fires in sequence during Replay Classified);
        a segment referencing an action_name absent from `project_actions` is
        flagged but not fatal -- Replay Classified itself just logs and skips
        it, same no-surprises spirit as run_engine.py's node handlers."""
        warnings = []
        n = len(self.events)
        prev_end = 0
        ordered = sorted(self.segments, key=lambda s: s.start_index)
        for seg in ordered:
            if seg.start_index < 0 or seg.end_index > n or seg.end_index <= seg.start_index:
                warnings.append(
                    f"segment {seg.label or seg.action_name!r}: invalid range "
                    f"[{seg.start_index}, {seg.end_index}) for {n} event(s)")
            elif seg.start_index < prev_end:
                warnings.append(
                    f"segment {seg.label or seg.action_name!r}: overlaps the previous segment "
                    f"(starts at {seg.start_index}, previous ends at {prev_end})")
            if seg.action_name not in project_actions:
                warnings.append(f"segment {seg.label or seg.action_name!r}: unknown action {seg.action_name!r}")
            prev_end = max(prev_end, seg.end_index)
        return warnings


class RunNodeKind(str, Enum):
    ACTION = "action"   # runs one already-defined Action (by name) against the device
    DELAY = "delay"      # waits `frames` frames, no wire message -- same unit as PrimitiveEvent.WAIT
    REPEAT = "repeat"     # runs its "body"-edge target's subgraph to completion `times` times,
                          # then continues once through its "after"-edge target, if any
    COMPARE = "compare"    # crops the live frame to a stored ImageTemplate's region and compares it;
                           # fires its "match" edge or its "no_match" edge depending on the result
                           # (see ImageTemplate.matches and run_engine.py's _run_node)
    FIND_TEMPLATE = "find_template"   # searches the whole live frame for a stored ImageTemplate,
                           # regardless of where it was originally captured; fires its "found" edge
                           # (having stashed the best-matching (x, y) for the executor to hand out)
                           # or its "not_found" edge if nothing over threshold turned up
                           # (see ImageTemplate.find and run_engine.py's _run_node)


@dataclass
class RunNode:
    id: str
    kind: RunNodeKind
    x: float = 0.0    # canvas position -- authoring layout only, has no effect on execution
    y: float = 0.0
    action_name: str = ""   # ACTION only
    frames: int = 0          # DELAY only
    times: int = 1            # REPEAT only
    template_name: str = ""   # COMPARE and FIND_TEMPLATE only

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind.value, "x": self.x, "y": self.y}
        if self.kind == RunNodeKind.ACTION:
            d["action_name"] = self.action_name
        elif self.kind == RunNodeKind.DELAY:
            d["frames"] = self.frames
        elif self.kind == RunNodeKind.REPEAT:
            d["times"] = self.times
        elif self.kind in (RunNodeKind.COMPARE, RunNodeKind.FIND_TEMPLATE):
            d["template_name"] = self.template_name
        return d

    @staticmethod
    def from_dict(d: dict) -> "RunNode":
        return RunNode(
            id=d["id"], kind=RunNodeKind(d["kind"]), x=d.get("x", 0.0), y=d.get("y", 0.0),
            action_name=d.get("action_name", ""), frames=d.get("frames", 0), times=d.get("times", 1),
            template_name=d.get("template_name", ""),
        )


@dataclass
class RunEdge:
    id: str
    source: str   # RunNode.id
    target: str   # RunNode.id
    # "out" for a plain fork edge (any source that isn't REPEAT/COMPARE/FIND_TEMPLATE, or one of
    # those that hasn't been assigned a role yet). Meaningful only when `source` is a REPEAT node
    # ("body" marks the one edge that starts the loop body, "after" the one edge that runs once
    # after all iterations finish), a COMPARE node ("match"/"no_match" mark the one edge each that
    # fires depending on the comparison result), or a FIND_TEMPLATE node ("found"/"not_found",
    # same spirit as COMPARE's). See GameRun docstring for why these node kinds need this and no
    # other kind does.
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
    finished before it starts). Two node kinds aren't just fork/join: REPEAT
    repeats its "body" edge's target subgraph to completion `times` times, then
    fires its single "after" edge once; COMPARE crops the live frame to a stored
    ImageTemplate's region, compares it, and fires its single "match" edge or its
    single "no_match" edge depending on the result -- an if/else condition for
    scripting game-run logic off of what's currently on screen (see RunEdge.via,
    ImageTemplate.matches, run_engine.py's _run_node). FIND_TEMPLATE is COMPARE's
    "where is it" sibling: instead of testing one fixed region it searches the
    whole live frame for a stored ImageTemplate and fires its single "found" edge
    or its single "not_found" edge, stashing the best match's (x, y) -- in the
    project's reference resolution -- on the executor for the caller to read back
    (see ImageTemplate.find, run_engine.py's GameRunExecutor.last_found). There's
    no explicit start/end node kind -- a node with no incoming edges is a root and
    starts immediately (multiple roots start in parallel); a node with no
    outgoing edges just ends its branch.
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

    def validate(self, project_actions: dict, project_templates: Optional[dict] = None) -> list:
        """Static authoring-time checks. Returns human-readable warnings, empty
        if the graph looks internally consistent. Does not catch every
        possible malformed graph (e.g. a node shared between a repeat body and
        the outer graph) -- see run_engine.py's module docstring.
        `project_templates` defaults to empty (every COMPARE node reference then
        warns) rather than being required, so existing callers that only pass
        `project_actions` keep working."""
        project_templates = project_templates or {}
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
            elif node.kind == RunNodeKind.COMPARE:
                if node.template_name not in project_templates:
                    warnings.append(f"node {node.id}: unknown template {node.template_name!r}")
                if len(self.outgoing(node.id, via="match")) > 1:
                    warnings.append(f"node {node.id}: compare has more than one match connection")
                if len(self.outgoing(node.id, via="no_match")) > 1:
                    warnings.append(f"node {node.id}: compare has more than one no_match connection")
            elif node.kind == RunNodeKind.FIND_TEMPLATE:
                if node.template_name not in project_templates:
                    warnings.append(f"node {node.id}: unknown template {node.template_name!r}")
                if len(self.outgoing(node.id, via="found")) > 1:
                    warnings.append(f"node {node.id}: find_template has more than one found connection")
                if len(self.outgoing(node.id, via="not_found")) > 1:
                    warnings.append(f"node {node.id}: find_template has more than one not_found connection")
            else:
                for e in self.outgoing(node.id):
                    if e.via != "out":
                        warnings.append(f"edge {e.id}: via={e.via!r} is only valid from a repeat, compare, or find_template node")
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
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""
    package: str = ""
    activity: str = ""
    serial: str = ""
    host: str = "127.0.0.1"
    port: int = 27183
    reference_width: int = 0
    reference_height: int = 0
    action_match_tolerance_px: int = 30   # see ACTION_CLASSIFICATION_DESIGN.md G8 -- position
                                           # tolerance find_matching_action uses to recognize a
                                           # gesture against an existing action's own recording
    time_scale: float = 1.0   # see ACTION_CLASSIFICATION_DESIGN.md G11 -- multiplies every
                              # WAIT/DELAY frame's real-ms duration (connection.FRAME_MS) at
                              # send/replay time. Position is already device-independent via
                              # LiveConnection.send_primitive's automatic resolution rescale;
                              # this is the one factor that genuinely can't be auto-detected
                              # (a different device's game-logic speed), so a recipient of a
                              # shared project tunes this by hand for their own device -- 1.0
                              # reproduces the original author's pacing exactly.
    actions: dict = field(default_factory=dict)   # dict[str, Action]
    runs: dict = field(default_factory=dict)        # dict[str, GameRun]
    templates: dict = field(default_factory=dict)    # dict[str, ImageTemplate]
    hud_regions: dict = field(default_factory=dict)   # dict[str, HudRegion]
    hud_region_combos: dict = field(default_factory=dict)   # dict[str, HudRegionCombo]

    def add_action(self, action: Action) -> None:
        self.actions[action.name] = action

    def remove_action(self, name: str) -> None:
        self.actions.pop(name, None)

    def rename_action(self, old_name: str, new_name: str) -> int:
        """Renames an action project-wide: the `actions` dict key, the Action's own
        `.name`, and every HudRegion.action_name/release_action_name, HudRegionCombo.action_name,
        and RunNode.action_name reference across every GameRun that named `old_name` (see
        ACTION_CLASSIFICATION_DESIGN.md G1 -- a bare free-text rename left every one of those
        silently pointing at a name that no longer resolves to anything, and the next
        classify+propose cycle would just re-create a new action under the orphaned old name).
        Returns the number of references updated (not counting the action definition itself),
        for the caller to log. Raises KeyError if `old_name` isn't an existing action, ValueError
        if `new_name` already names a *different* action."""
        if old_name not in self.actions:
            raise KeyError(old_name)
        if new_name != old_name and new_name in self.actions:
            raise ValueError(f"action {new_name!r} already exists")
        if new_name == old_name:
            return 0

        action = self.actions.pop(old_name)
        action.name = new_name
        self.actions[new_name] = action

        updated = 0
        for region in self.hud_regions.values():
            if region.action_name == old_name:
                region.action_name = new_name
                updated += 1
            if region.release_action_name == old_name:
                region.release_action_name = new_name
                updated += 1
        for combo in self.hud_region_combos.values():
            if combo.action_name == old_name:
                combo.action_name = new_name
                updated += 1
        for run in self.runs.values():
            for node in run.nodes.values():
                if node.kind == RunNodeKind.ACTION and node.action_name == old_name:
                    node.action_name = new_name
                    updated += 1
        return updated

    def add_run(self, run: GameRun) -> None:
        self.runs[run.name] = run

    def remove_run(self, name: str) -> None:
        self.runs.pop(name, None)

    def add_template(self, template: ImageTemplate) -> None:
        self.templates[template.name] = template

    def remove_template(self, name: str) -> None:
        self.templates.pop(name, None)

    def add_hud_region(self, region: HudRegion) -> None:
        self.hud_regions[region.name] = region

    def remove_hud_region(self, name: str) -> None:
        self.hud_regions.pop(name, None)

    def rename_hud_region(self, old_name: str, new_name: str) -> int:
        """Renames a HUD region project-wide: the `hud_regions` dict key, the region's own
        `.name`, and every HudRegionCombo.region_names entry naming `old_name`. Same rationale
        as rename_action -- a bare free-text rename would silently break any combo referencing
        this region. Returns the number of combo references updated. Raises KeyError if
        `old_name` isn't an existing region, ValueError if `new_name` already names a
        *different* region."""
        if old_name not in self.hud_regions:
            raise KeyError(old_name)
        if new_name != old_name and new_name in self.hud_regions:
            raise ValueError(f"HUD region {new_name!r} already exists")
        if new_name == old_name:
            return 0

        region = self.hud_regions.pop(old_name)
        region.name = new_name
        self.hud_regions[new_name] = region

        updated = 0
        for combo in self.hud_region_combos.values():
            updated += sum(1 for n in combo.region_names if n == old_name)
            combo.region_names = [new_name if n == old_name else n for n in combo.region_names]
        return updated

    def add_hud_region_combo(self, combo: HudRegionCombo) -> None:
        self.hud_region_combos[combo.name] = combo

    def remove_hud_region_combo(self, name: str) -> None:
        self.hud_region_combos.pop(name, None)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "package": self.package,
            "activity": self.activity,
            "serial": self.serial,
            "host": self.host,
            "port": self.port,
            "reference_resolution": {"width": self.reference_width, "height": self.reference_height},
            "action_match_tolerance_px": self.action_match_tolerance_px,
            "time_scale": self.time_scale,
            "actions": [a.to_dict() for a in self.actions.values()],
            "runs": [r.to_dict() for r in self.runs.values()],
            "templates": [t.to_dict() for t in self.templates.values()],
            "hud_regions": [r.to_dict() for r in self.hud_regions.values()],
            "hud_region_combos": [c.to_dict() for c in self.hud_region_combos.values()],
        }

    @staticmethod
    def from_dict(d: dict) -> "Project":
        res = d.get("reference_resolution", {})
        p = Project(
            name=d["name"],
            id=d.get("id") or uuid.uuid4().hex,
            description=d.get("description", ""),
            created_at=d.get("created_at") or datetime.now(timezone.utc).isoformat(),
            updated_at=d.get("updated_at", ""),
            package=d.get("package", ""),
            activity=d.get("activity", ""),
            serial=d.get("serial", ""),
            host=d.get("host", "127.0.0.1"),
            port=d.get("port", 27183),
            reference_width=res.get("width", 0),
            reference_height=res.get("height", 0),
            action_match_tolerance_px=d.get("action_match_tolerance_px", 30),
            time_scale=d.get("time_scale", 1.0),
        )
        for a in d.get("actions", []):
            p.add_action(Action.from_dict(a))
        for r in d.get("runs", []):
            p.add_run(GameRun.from_dict(r))
        for t in d.get("templates", []):
            p.add_template(ImageTemplate.from_dict(t))
        for hr in d.get("hud_regions", []):
            p.add_hud_region(HudRegion.from_dict(hr))
        for c in d.get("hud_region_combos", []):
            p.add_hud_region_combo(HudRegionCombo.from_dict(c))
        return p

    def copy(self) -> "Project":
        return copy.deepcopy(self)
