"""Records real touches made directly on the physical device, via `adb shell
getevent` -- independent of irobot/irobot_server entirely (no APK change, no
mirror involved; a genuine finger-on-glass touch never passes through
irobot's socket protocol at all). Verified live against a real device before
building this: raw ABS_MT_* multitouch events arrive with clean, complete
down/move/up cycles and sub-millisecond timestamps.

Feeds the same model.PrimitiveEvent/Action vocabulary the rest of this IDE
uses -- a recorded gesture becomes an Action's events like any other, just
sourced from a physical touch instead of a canvas click.

Everything here except `DeviceEventRecorder` itself (which owns the `adb`
subprocess and a background thread) is a pure function/class with no I/O, so
it's testable against canned getevent text with no device attached -- see
tests/test_device_recorder.py.
"""
from __future__ import annotations

import re
import subprocess
import threading

from .connection import FRAME_MS
from .model import EventKind, PrimitiveEvent

TRACKING_ID_UP = 0xFFFFFFFF

_LINE_RE = re.compile(r"^\[\s*(?P<ts>\d+\.\d+)\]\s+(?P<dev>\S+):\s+(?P<type>\S+)\s+(?P<code>\S+)\s+(?P<value>\S+)\s*$")
_ADD_DEVICE_RE = re.compile(r"^add device \d+:\s+(?P<dev>\S+)\s*$")
_NAME_RE = re.compile(r'^\s*name:\s*"(?P<name>.*)"\s*$')
_AXIS_RE = re.compile(
    r"^\s*(?P<code>ABS_MT_POSITION_X|ABS_MT_POSITION_Y|ABS_X|ABS_Y)\s*:\s*value\s+-?\d+,\s*min\s+-?\d+,\s*max\s+(?P<max>-?\d+)")


class RecordedTouch:
    """One reconstructed touch transition. `kind` is "down"/"move"/"up".
    `x`/`y` are raw touch-panel units (not yet scaled to any resolution).
    `t` is seconds since the first event this capture saw."""
    __slots__ = ("kind", "slot", "x", "y", "t")

    def __init__(self, kind, slot, x, y, t):
        self.kind, self.slot, self.x, self.y, self.t = kind, slot, x, y, t

    def __repr__(self):
        return f"RecordedTouch({self.kind!r}, slot={self.slot}, x={self.x}, y={self.y}, t={self.t:.3f})"


class TouchStateMachine:
    """Incremental parser: feed one `getevent -lt` line at a time via
    `feed_line()`; it returns the RecordedTouch objects finalized by that
    line (non-empty only right after a SYN_REPORT that closed out a frame of
    changes). Reconstructs Android's Type-B multitouch protocol (ABS_MT_SLOT
    + ABS_MT_TRACKING_ID demux multiple concurrent fingers), with a
    single-touch/protocol-A fallback (bare ABS_X/ABS_Y + BTN_TOUCH) for
    devices that never emit slot/tracking-id events at all.

    Auto-detects the touchscreen input node from the "add device N: <path>"
    / "name: ..." header lines `getevent -lt` prints before streaming events
    (matches a name containing "touch", case-insensitive) unless
    `touch_device_path` is given explicitly -- pass it when the auto-detect
    name heuristic doesn't match a given device's touch controller name.
    """

    def __init__(self, touch_device_path: str | None = None):
        self.touch_device_path = touch_device_path
        self._pending_add_device = None
        self._start_time = None
        self._current_slot = 0
        self._slot_tracking = {}
        self._slot_pos = {}
        self._pending_down = set()
        self._pending_move = set()
        self._pending_up = set()

    def feed_line(self, line: str) -> list:
        line = line.rstrip("\n")
        if not line:
            return []

        add_m = _ADD_DEVICE_RE.match(line)
        if add_m:
            self._pending_add_device = add_m.group("dev")
            return []
        name_m = _NAME_RE.match(line)
        if name_m:
            if (self.touch_device_path is None and self._pending_add_device
                    and "touch" in name_m.group("name").lower()):
                self.touch_device_path = self._pending_add_device
            return []

        m = _LINE_RE.match(line)
        if not m:
            return []
        dev = m.group("dev")
        if self.touch_device_path is not None and dev != self.touch_device_path:
            return []  # an event from some other input node (keys, headset jack, ...)

        ts = float(m.group("ts"))
        if self._start_time is None:
            self._start_time = ts
        t = ts - self._start_time
        ev_type, code, value = m.group("type"), m.group("code"), m.group("value")

        if ev_type == "EV_ABS":
            return self._feed_abs(code, value, t)
        if ev_type == "EV_KEY" and code == "BTN_TOUCH":
            self._feed_btn_touch(value)
            return []
        if ev_type == "EV_SYN" and code == "SYN_REPORT":
            return self._flush(t)
        return []

    def _feed_abs(self, code: str, value: str, t: float) -> list:
        if code == "ABS_MT_SLOT":
            self._current_slot = int(value, 16)
        elif code == "ABS_MT_TRACKING_ID":
            self._feed_tracking_id(int(value, 16))
        elif code in ("ABS_MT_POSITION_X", "ABS_X"):
            slot = self._current_slot if code == "ABS_MT_POSITION_X" else 0
            self._slot_pos.setdefault(slot, [None, None])[0] = int(value, 16)
            if slot not in self._pending_down:
                self._pending_move.add(slot)
        elif code in ("ABS_MT_POSITION_Y", "ABS_Y"):
            slot = self._current_slot if code == "ABS_MT_POSITION_Y" else 0
            self._slot_pos.setdefault(slot, [None, None])[1] = int(value, 16)
            if slot not in self._pending_down:
                self._pending_move.add(slot)
        return []

    def _feed_tracking_id(self, tid: int) -> None:
        slot = self._current_slot
        if tid == TRACKING_ID_UP:
            if self._slot_tracking.get(slot) is not None:
                self._pending_up.add(slot)
                self._pending_down.discard(slot)
                self._pending_move.discard(slot)
            self._slot_tracking[slot] = None
        else:
            self._slot_tracking[slot] = tid
            self._pending_down.add(slot)
            self._pending_up.discard(slot)
            self._pending_move.discard(slot)

    def _feed_btn_touch(self, value: str) -> None:
        # fallback for protocol-A/single-touch devices with no ABS_MT_TRACKING_ID
        # at all. Devices that DO send tracking ids also send BTN_TOUCH
        # alongside them (verified against a real capture); this is a no-op
        # in that case because slot 0's tracking state is already set by
        # _feed_tracking_id before/after this fires, so `currently_down`
        # already matches -- no double-counting.
        currently_down = self._slot_tracking.get(0) is not None
        if value == "DOWN" and not currently_down:
            self._slot_tracking[0] = 1
            self._pending_down.add(0)
            self._pending_up.discard(0)
        elif value == "UP" and currently_down:
            self._slot_tracking[0] = None
            self._pending_up.add(0)
            self._pending_down.discard(0)
            self._pending_move.discard(0)

    def _flush(self, t: float) -> list:
        flushed = []
        for slot in self._pending_down:
            pos = self._slot_pos.get(slot, [None, None])
            flushed.append(RecordedTouch("down", slot, pos[0], pos[1], t))
        for slot in self._pending_move:
            pos = self._slot_pos.get(slot, [None, None])
            if pos[0] is not None and pos[1] is not None:
                flushed.append(RecordedTouch("move", slot, pos[0], pos[1], t))
        for slot in self._pending_up:
            pos = self._slot_pos.get(slot, [None, None])
            flushed.append(RecordedTouch("up", slot, pos[0], pos[1], t))
        self._pending_down.clear()
        self._pending_move.clear()
        self._pending_up.clear()
        return flushed


def parse_getevent_stream(lines, touch_device_path: str | None = None) -> list:
    """Batch convenience wrapper over TouchStateMachine, mainly for tests and
    for converting an already-captured log file."""
    machine = TouchStateMachine(touch_device_path)
    touches = []
    for line in lines:
        touches.extend(machine.feed_line(line))
    return touches


def parse_axis_ranges(pl_output: str):
    """Parses `adb shell getevent -pl` output and returns (x_max, y_max) for
    the touchscreen device block (name containing "touch", case-insensitive),
    or None if no such block, or no axis info, was found. This is the raw
    touch-panel coordinate range gesture_to_events() scales from -- often but
    not always identical to the device's real screen resolution, so it must
    be probed per-device rather than assumed equal to it."""
    best = None
    current_name = None
    current_x_max = None
    current_y_max = None

    def _flush_if_touch():
        if current_name and "touch" in current_name.lower() and current_x_max is not None and current_y_max is not None:
            return (current_x_max, current_y_max)
        return None

    for line in pl_output.splitlines():
        name_m = _NAME_RE.match(line)
        if name_m:
            found = _flush_if_touch()
            if found:
                best = found
            current_name = name_m.group("name")
            current_x_max = None
            current_y_max = None
            continue
        axis_m = _AXIS_RE.match(line)
        if axis_m:
            code, max_val = axis_m.group("code"), int(axis_m.group("max"))
            if code in ("ABS_MT_POSITION_X", "ABS_X"):
                current_x_max = max_val
            elif code in ("ABS_MT_POSITION_Y", "ABS_Y"):
                current_y_max = max_val

    found = _flush_if_touch()
    if found:
        best = found
    return best


_VIEWPORT_ORIENTATION_RE = re.compile(r"Viewport INTERNAL:.*?orientation=(?P<rotation>\d+)")


def parse_touch_rotation(dumpsys_input_output: str):
    """Parses `adb shell dumpsys input` output for the internal display's
    current rotation (Surface.ROTATION_0/90/180/270, i.e. 0/1/2/3), or None
    if not found. This is not cosmetic -- confirmed against a real device
    whose physical touch panel is natively portrait (raw ABS_MT_POSITION_X/Y
    max 1199x2669) while the display was showing landscape content: Android's
    InputReader applies exactly this rotation between what the raw digitizer
    reports and the logical coordinates MotionEvent (and thus
    CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT's target space) uses. Treating raw
    touch-panel coordinates as already being in logical space -- what an
    earlier version of gesture_to_events did -- silently produces a rotated,
    wrong position: a real recorded "jump" button tap at raw (123, 2462) was
    coming out as roughly (274, 1107) instead of the correct ~(2416, 1073)
    (which apply_rotation + scaling below reproduces to within a few pixels)."""
    m = _VIEWPORT_ORIENTATION_RE.search(dumpsys_input_output)
    if not m:
        return None
    return int(m.group("rotation"))


def apply_rotation(x: int, y: int, raw_x_max: int, raw_y_max: int, rotation: int):
    """Maps one raw touch-panel sample through the display's current rotation
    (0/1/2/3 = Surface.ROTATION_0/90/180/270) into that display's logical
    axis order. Returns (x, y, x_max, y_max) -- the last two are the raw-unit
    bounds of the OUTPUT x/y (axes swap for a 90 degree turn either way), so
    a caller scales with `x / x_max * ref_w, y / y_max * ref_h` regardless of
    rotation, never `raw_x_max`/`raw_y_max` directly."""
    if rotation == 1:  # ROTATION_90
        return y, raw_x_max - x, raw_y_max, raw_x_max
    if rotation == 2:  # ROTATION_180
        return raw_x_max - x, raw_y_max - y, raw_x_max, raw_y_max
    if rotation == 3:  # ROTATION_270
        return raw_y_max - y, x, raw_y_max, raw_x_max
    return x, y, raw_x_max, raw_y_max  # ROTATION_0, or an unrecognized value


def segment_into_gestures(touches: list) -> list:
    """Groups a flat RecordedTouch stream into per-gesture runs: each gesture
    is one slot's contiguous down -> [move...] -> up sequence. Multiple
    concurrent fingers naturally become separate, interleaved gestures since
    they're tracked by slot. A gesture still open when the stream ends
    (recording stopped mid-touch) is included anyway, without its "up"."""
    open_gestures = {}
    finished = []
    for touch in touches:
        if touch.kind == "down":
            open_gestures[touch.slot] = [touch]
        elif touch.slot in open_gestures:
            open_gestures[touch.slot].append(touch)
            if touch.kind == "up":
                finished.append(open_gestures.pop(touch.slot))
    finished.extend(open_gestures.values())
    return finished


def _scale_touch(touch, raw_x_max: int, raw_y_max: int, ref_w: int, ref_h: int, rotation: int):
    if touch.x is None or touch.y is None:
        return None, None
    x, y, x_max, y_max = apply_rotation(touch.x, touch.y, raw_x_max, raw_y_max, rotation)
    return round(x / x_max * ref_w), round(y / y_max * ref_h)


def _gesture_to_timed_events(gesture: list, raw_x_max: int, raw_y_max: int, ref_w: int, ref_h: int,
                              pointer_id: int, tap_threshold_px: int, rotation: int,
                              tap_duration_s: float = 0.15) -> list:
    """Converts one gesture into [(t, PrimitiveEvent), ...] -- no WAIT events
    inserted here, since that only makes sense once every gesture in a
    recording session has been merged into one chronological timeline (see
    merge_gestures_into_events). `t` is the same relative-to-capture-start
    seconds RecordedTouch.t already carries.

    A gesture only collapses to a single TAP when it's BOTH short in
    movement (< tap_threshold_px) AND short in duration (< tap_duration_s).
    Duration matters on its own: a finger held perfectly still -- e.g.
    holding a d-pad direction while a second finger taps something else,
    the exact "right + jump" case this was built for -- has zero movement
    but is a deliberate hold, not an instant tap; judging by movement alone
    would silently collapse a 200ms hold into a TAP and lose it entirely."""
    if not gesture or raw_x_max <= 0 or raw_y_max <= 0:
        return []

    first_x, first_y = gesture[0].x, gesture[0].y
    max_delta = 0
    if first_x is not None and first_y is not None:
        for touch in gesture:
            if touch.x is not None and touch.y is not None:
                max_delta = max(max_delta, abs(touch.x - first_x) + abs(touch.y - first_y))
    duration = gesture[-1].t - gesture[0].t

    if max_delta < tap_threshold_px and duration < tap_duration_s:
        x, y = _scale_touch(gesture[0], raw_x_max, raw_y_max, ref_w, ref_h, rotation)
        return [(gesture[0].t, PrimitiveEvent(kind=EventKind.TAP, pointer_id=pointer_id, x=x, y=y))]

    timed = []
    for touch in gesture:
        x, y = _scale_touch(touch, raw_x_max, raw_y_max, ref_w, ref_h, rotation)
        if touch.kind == "down":
            timed.append((touch.t, PrimitiveEvent(kind=EventKind.PRESS, pointer_id=pointer_id, x=x, y=y)))
        elif touch.kind == "move":
            if x is not None and y is not None:
                timed.append((touch.t, PrimitiveEvent(kind=EventKind.MOVE, pointer_id=pointer_id, x=x, y=y)))
        elif touch.kind == "up":
            timed.append((touch.t, PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=pointer_id)))
    return timed


def _insert_wait_gaps(timed_events: list) -> list:
    """Given [(t, PrimitiveEvent), ...] already in chronological order,
    returns the flat PrimitiveEvent list with a WAIT inserted between any two
    consecutive events whose real recorded gap rounds to >0 frames (same
    FRAME_MS assumption connection.py's own WAIT playback makes -- there's no
    real frame-rate handshake on the wire, see its comment)."""
    events = []
    prev_t = None
    for t, event in timed_events:
        if prev_t is not None:
            gap_frames = round((t - prev_t) * 1000 / FRAME_MS)
            if gap_frames > 0:
                events.append(PrimitiveEvent(kind=EventKind.WAIT, pointer_id=event.pointer_id, frames=gap_frames))
        events.append(event)
        prev_t = t
    return events


def gesture_to_events(gesture: list, raw_x_max: int, raw_y_max: int, ref_w: int, ref_h: int,
                       pointer_id: int = 0, tap_threshold_px: int = 24, rotation: int = 0,
                       tap_duration_s: float = 0.15) -> list:
    """Converts one recorded gesture (raw touch-panel coordinates) into a
    PrimitiveEvent sequence in the project's reference resolution. `rotation`
    (0/1/2/3 = Surface.ROTATION_0/90/180/270, see parse_touch_rotation) is
    applied via apply_rotation() BEFORE scaling -- passing 0 when the display
    is actually rotated reproduces the real bug this was built to fix (a
    landscape game on a portrait-native panel came out mirrored/transposed,
    not just imprecise). A gesture becomes a single TAP only when it's both
    short in movement (< tap_threshold_px) AND short in duration
    (< tap_duration_s, default 150ms) -- see _gesture_to_timed_events for why
    duration alone matters (a held-still finger isn't a tap). Anything else
    becomes PRESS -> MOVE... -> RELEASE with WAIT gaps reflecting the real
    recorded timing. Does not downsample/simplify a long drag's move
    samples -- every recorded sample becomes its own MOVE event; trim via
    the inspector if that's too many.

    For a whole recording session with more than one gesture (e.g. holding
    one button while tapping another), use merge_gestures_into_events instead
    -- this function's WAIT gaps are only correct within a single gesture."""
    timed = _gesture_to_timed_events(gesture, raw_x_max, raw_y_max, ref_w, ref_h,
                                      pointer_id, tap_threshold_px, rotation, tap_duration_s)
    return _insert_wait_gaps(timed)


def merge_gestures_into_events(gestures: list, raw_x_max: int, raw_y_max: int, ref_w: int, ref_h: int,
                                tap_threshold_px: int = 24, rotation: int = 0,
                                tap_duration_s: float = 0.15) -> list:
    """Merges every gesture from one recording session into a single
    chronologically-ordered PrimitiveEvent sequence for one Action -- the
    right shape for "hold right while tapping jump" recorded as one session,
    rather than forcing a name onto each separate touch. Each gesture keeps
    its own `pointer_id`, taken directly from its raw ABS_MT_SLOT (ordinarily
    small integers reused sequentially by the digitizer once a finger lifts,
    same as this project's own pointer-sharing convention for mutually
    exclusive holds -- see plan §7.4), so two genuinely concurrent touches
    (different slots) stay on independent pointers exactly like a real
    multi-finger chord, while two sequential taps that happen to reuse the
    same slot still round-trip correctly (PRESS/RELEASE never overlap for a
    single pointer_id). WAIT gaps are computed once across the FULL merged
    timeline, not per gesture, so real inter-gesture timing (e.g. "jump was
    tapped 400ms after right was first held") is preserved. See
    _gesture_to_timed_events for why a held-still finger (e.g. "right")
    correctly becomes PRESS/.../RELEASE rather than collapsing to a TAP."""
    all_timed = []
    for gesture in gestures:
        if not gesture:
            continue
        pointer_id = gesture[0].slot
        all_timed.extend(_gesture_to_timed_events(
            gesture, raw_x_max, raw_y_max, ref_w, ref_h, pointer_id, tap_threshold_px, rotation, tap_duration_s))
    all_timed.sort(key=lambda pair: pair[0])
    return _insert_wait_gaps(all_timed)


class DeviceEventRecorder:
    """Owns the `adb shell getevent -lt` subprocess and a background thread
    feeding its output into a TouchStateMachine. Call start(), let the user
    touch the device, then stop() to get back every RecordedTouch seen."""

    def __init__(self, adb_path: str = "adb", serial: str | None = None):
        self.adb_path = adb_path
        self.serial = serial
        self._proc = None
        self._thread = None
        self._lock = threading.Lock()
        self._machine = None
        self._touches = []

    def _adb_cmd(self, *args: str) -> list:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._adb_cmd("shell", "getevent", "-lt"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        self._machine = TouchStateMachine()
        self._touches = []
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            flushed = self._machine.feed_line(line)
            if flushed:
                with self._lock:
                    self._touches.extend(flushed)

    def stop(self) -> list:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            return list(self._touches)

    def recorded_touches(self) -> list:
        with self._lock:
            return list(self._touches)

    @property
    def touch_device_path(self):
        return self._machine.touch_device_path if self._machine else None

    def probe_axis_ranges(self):
        """Runs `adb shell getevent -pl` (a separate one-shot call, not the
        live -lt stream this recorder otherwise owns) and returns (x_max,
        y_max) for the touchscreen, or None if it couldn't be determined."""
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "getevent", "-pl"),
                capture_output=True, text=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return parse_axis_ranges(result.stdout)

    def probe_rotation(self):
        """Runs `adb shell dumpsys input` and returns the current display
        rotation (0/1/2/3, see parse_touch_rotation), or None if it couldn't
        be determined. Must be applied (via apply_rotation, inside
        gesture_to_events) whenever the touch panel's native orientation
        doesn't match the display's current one -- see parse_touch_rotation's
        docstring for the real bug this fixes."""
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "dumpsys", "input"),
                capture_output=True, text=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return parse_touch_rotation(result.stdout)
