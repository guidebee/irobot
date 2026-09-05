"""Live connection to a running `irobot` process's agent ports.

Thin wrapper around tools/agent_client.py's wire helpers -- this module owns
no wire-format knowledge of its own (see docs/opengym_implementation_plan.md
§5's "protocol.py ... both import this" intent; until that extraction
happens, this imports agent_client.py directly rather than re-deriving the
message shapes). Two responsibilities:

  1. A background thread that keeps the most recent video frame available
     (the video channel is push-only/unsolicited -- see plan §3.2 -- so
     "latest frame" is genuinely the freshest thing on offer, not something
     that can be requested on demand).
  2. Resolving a model.Action's PrimitiveEvents into real touch/key wire
     messages and sending them, tracking which pointer_ids are currently
     held so a RELEASE without a matching PRESS is a local no-op (mirrors
     the runtime behavior planned for the eventual Gym env, plan §7.1).
"""
from __future__ import annotations

import socket
import threading
import time

from ._agent_client import agent_client as ac
from .model import Action, EventKind, PrimitiveEvent, scale_point

FRAME_MS = 33  # assumed ms/frame for WAIT events -- no real frame-rate handshake
                # exists on the wire yet; see docs/irobot_gym_ide_design.md "Known limitations"


class LiveConnection:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._control_sock = None
        self._video_sock = None
        self._reader_thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest = None          # (width, height, pixels: bytes) grayscale opencv_mat frame
        self._latest_thumbnail = None  # (width, height, pixels: bytes, phash: bytes) color screen_shot frame
        self._latest_resolution = None  # (width, height) from BLOB_MSG_TYPE_RESOLUTION, or None if not received yet
        self._held_pointers = set()  # pointer_ids currently DOWN, per this connection's own bookkeeping
        self.time_scale = 1.0  # multiplies every WAIT's real-ms duration -- see model.Project.time_scale;
                                # a caller (MainWindow) syncs this from the loaded project, not this class

    # -- lifecycle ----------------------------------------------------

    def connect(self) -> None:
        self._control_sock = socket.create_connection((self.host, self.port + 1), timeout=5)
        self._video_sock = socket.create_connection((self.host, self.port + 2), timeout=5)
        self._video_sock.settimeout(None)
        self._stop.clear()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def disconnect(self) -> None:
        self._stop.set()
        for sock in (self._control_sock, self._video_sock):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._control_sock = None
        self._video_sock = None
        self._held_pointers.clear()

    @property
    def connected(self) -> bool:
        return self._control_sock is not None and self._video_sock is not None

    # -- video --------------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg_type, buffers = ac.read_blob_message(self._video_sock)
            except (OSError, ConnectionError):
                break
            if not buffers:
                continue
            if msg_type == ac.BLOB_MSG_TYPE_RESOLUTION:
                width, height, _pixels = buffers[0]
                with self._lock:
                    self._latest_resolution = (width, height)
                continue
            if msg_type == ac.BLOB_MSG_TYPE_SCREEN_SHOT:
                if not buffers:
                    continue
                width, height, pixels = buffers[0]
                phash = buffers[1][2] if len(buffers) > 1 else b""
                with self._lock:
                    self._latest_thumbnail = (width, height, pixels, phash)
                continue
            if msg_type != ac.BLOB_MSG_TYPE_OPENCV_MAT:
                continue
            width, height, pixels = buffers[0]
            with self._lock:
                self._latest = (width, height, pixels)

    def latest_frame(self):
        """Returns (width, height, grayscale ndarray) or None if no frame has
        arrived yet. Imports numpy lazily so the rest of this module works
        without it (same lazy-import pattern agent_client.py itself uses)."""
        with self._lock:
            snapshot = self._latest
        if snapshot is None:
            return None
        import numpy as np
        width, height, pixels = snapshot
        frame = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width))
        return width, height, frame

    def latest_thumbnail(self):
        """Returns (width, height, color ndarray shape (h,w,3), phash bytes)
        from the AgentStream's BLOB_MSG_TYPE_SCREEN_SHOT messages, or None if
        none has arrived yet (older irobot builds never send this). Mirrors
        latest_frame()'s lazy numpy import and lock-protected snapshot."""
        with self._lock:
            snapshot = self._latest_thumbnail
        if snapshot is None:
            return None
        width, height, pixels, phash = snapshot
        if not pixels or not width or not height:
            return None
        import numpy as np
        channels = len(pixels) // (width * height)
        arr = np.frombuffer(pixels, dtype=np.uint8)
        color = arr.reshape((height, width, channels)) if channels > 1 else arr.reshape((height, width))
        return width, height, color, phash

    def latest_resolution(self):
        """Returns (width, height), the real device resolution as reported by
        BLOB_MSG_TYPE_RESOLUTION (see AgentManager::SendResolution), or None
        if irobot hasn't sent one yet -- older irobot builds without that
        message never will, so callers must keep working when this stays
        None forever (fall back to asking the user, as before)."""
        with self._lock:
            return self._latest_resolution

    # -- control --------------------------------------------------------

    def _send_control(self, msg: dict) -> None:
        """Sends one JSON control message. Every write to the control socket
        should go through this rather than a bare
        `ac.send_json(self._control_sock, ...)`, so there's one place to
        change if the control wire format needs adjusting again."""
        ac.send_json(self._control_sock, msg)

    def send_primitive(self, event: PrimitiveEvent, ref_w: int, ref_h: int) -> str | None:
        """Sends one PrimitiveEvent's wire message(s). Returns None on success,
        or a short human-readable reason it was skipped as a no-op (never
        raises for a malformed-but-well-typed event -- see module docstring).

        `ref_w`/`ref_h` are the resolution `event`'s (x, y) was authored/recorded against --
        NOT necessarily this live device's own real resolution (see model.Project.
        reference_width/height's docstring: a shared project can be opened against any
        device). When this connection has already received a BLOB_MSG_TYPE_RESOLUTION and
        it differs from `ref_w`/`ref_h`, (x, y) is rescaled (model.scale_point) into that
        real resolution before sending, and the *device's* resolution -- not `ref_w`/`ref_h`
        -- is sent as touch_message's screen_size, since irobot_server's PositionMapper.map()
        requires an exact match (see agent_client.touch_message's docstring) and would
        otherwise silently drop every event from a project authored on a different-resolution
        device. This is the mechanism that makes a shared, classified session/Game Run
        actually portable across devices (see ACTION_CLASSIFICATION_DESIGN.md G11) --
        `time_scale` (below) is the timing half of that same story, which can't be
        auto-detected the way resolution can and so is a per-project value a recipient tunes
        by hand."""
        if not self.connected:
            return "not connected"

        if event.kind == EventKind.WAIT:
            time.sleep(event.frames * FRAME_MS * self.time_scale / 1000.0)
            return None

        if event.kind == EventKind.KEY:
            keycode = event.keycode
            if keycode is None and event.key_name:
                keycode = ac.android_keycode(event.key_name)
            if keycode is None:
                return f"key event has no resolvable keycode (key_name={event.key_name!r})"
            self._send_control(ac.keycode_message(ac.ACTION_DOWN, keycode))
            self._send_control(ac.keycode_message(ac.ACTION_UP, keycode))
            return None

        if event.kind == EventKind.RELEASE and event.pointer_id not in self._held_pointers:
            return f"RELEASE on pointer {event.pointer_id} which was never pressed"
        if event.kind in (EventKind.MOVE,) and event.pointer_id not in self._held_pointers:
            return f"MOVE on pointer {event.pointer_id} which is not currently held"
        if event.kind == EventKind.PRESS and event.pointer_id in self._held_pointers:
            return f"PRESS on pointer {event.pointer_id} which is already held"

        action_for_kind = {
            EventKind.TAP: None,       # sent as DOWN then UP below
            EventKind.PRESS: ac.MOTION_ACTION_DOWN,
            EventKind.RELEASE: ac.MOTION_ACTION_UP,
            EventKind.MOVE: ac.MOTION_ACTION_MOVE,
        }[event.kind]

        x, y = event.x, event.y
        send_w, send_h = ref_w, ref_h
        device_res = self.latest_resolution()
        if device_res is not None and ref_w and ref_h and device_res != (ref_w, ref_h):
            device_w, device_h = device_res
            if x is not None and y is not None:
                x, y = scale_point(x, y, ref_w, ref_h, device_w, device_h)
            send_w, send_h = device_w, device_h

        if event.kind == EventKind.RELEASE and (x is None or y is None):
            x, y = 0, 0  # position is irrelevant for an UP; server only reads pointer id + action

        if event.kind == EventKind.TAP:
            buttons_down = ac.BUTTON_PRIMARY
            self._send_control(ac.touch_message(
                ac.MOTION_ACTION_DOWN, x, y, send_w, send_h, pointer_id=event.pointer_id, buttons=buttons_down))
            self._send_control(ac.touch_message(
                ac.MOTION_ACTION_UP, x, y, send_w, send_h, pointer_id=event.pointer_id, buttons=0))
        else:
            buttons = 0 if event.kind == EventKind.RELEASE else ac.BUTTON_PRIMARY
            self._send_control(ac.touch_message(
                action_for_kind, x, y, send_w, send_h, pointer_id=event.pointer_id, buttons=buttons))

        if event.kind == EventKind.PRESS:
            self._held_pointers.add(event.pointer_id)
        elif event.kind == EventKind.RELEASE:
            self._held_pointers.discard(event.pointer_id)
        return None

    def run_action(self, action: Action, ref_w: int, ref_h: int) -> list:
        """Sends every event in `action` in order. Returns a list of
        (event_index, reason) for any events skipped as no-ops."""
        skipped = []
        for i, event in enumerate(action.events):
            reason = self.send_primitive(event, ref_w, ref_h)
            if reason is not None:
                skipped.append((i, reason))
        return skipped

    def release_all_held(self, ref_w: int, ref_h: int) -> None:
        """Sends RELEASE for every pointer this connection believes is still
        held -- the "leaves before reset()" cleanup the plan doc's §7.1 notes
        a real Gym env must do; useful here so switching/testing actions in
        the IDE doesn't leak a phantom held finger into the next test."""
        for pointer_id in list(self._held_pointers):
            self.send_primitive(
                PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=pointer_id), ref_w, ref_h)
