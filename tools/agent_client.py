#!/usr/bin/env python3
"""
irobot AI-agent test client.

Talks to a running `irobot` client process over the two agent-only TCP ports
opened by AgentManager (see src/agent/agent_manager.cpp):

    control port = <--port> + 1   (default 27184)  JSON ControlMessage in
    video port   = <--port> + 2   (default 27185)  binary BlobMessage out

These are irobot's own ports/protocols for an external AI/automation client
-- separate from the Android device connection (adb) and from the human
control socket.

Subcommands:
    record <file.json>    capture local keyboard presses/releases AND
                          click/drag on the shown video (like a real
                          touchscreen -- see `interactive`), forward each
                          one live to the device, and save them with
                          relative timing. Requires --screen-size (see
                          `interactive` below for why).
    play   <file.json>   replay a recording by resending the same events
                          with the original timing. Accepts either this
                          script's own `record` output OR irobot's own
                          native recording (Ctrl+E in irobot.exe writes
                          events.json, covering touch events too -- see
                          the comment above cmd_play for details/caveats)
    stream                connect to the video port and display the live
                          frames (plus a perceptual-hash change indicator)
    interactive           like `stream`, but click/drag on the window to
                          send real touch events back to irobot -- use the
                          mirrored view like an actual phone touchscreen.
                          Requires --screen-size WIDTHxHEIGHT, exactly as
                          irobot itself prints at startup ("Initial
                          texture: WxH") -- see the comment above
                          cmd_interactive for why this can't be auto-
                          detected.

Install what you need:
    pip install pynput                  # for `record`
    pip install opencv-python numpy     # for `record` / `stream` / `interactive`
"""
import argparse
import json
import socket
import struct
import time

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 27183  # irobot's --port; control = port+1, video = port+2

# --- Android key/motion event constants ---
# see src/android/input.hpp (AndroidKeyEventAction, AndroidMotionEventAction)
# and src/android/keycodes.hpp (AndroidKeycode)
ACTION_DOWN = 0
ACTION_UP = 1

MOTION_ACTION_DOWN = 0
MOTION_ACTION_UP = 1
MOTION_ACTION_MOVE = 2
BUTTON_PRIMARY = 1  # AMOTION_EVENT_BUTTON_PRIMARY

# POINTER_ID_MOUSE (src/message/control_msg.hpp) is UINT64_C(-1). The
# server reads it via `(int) touch_event["pointer"]` then assigns that into
# a uint64_t field (src/message/control_msg.cpp), so sending the JSON
# number -1 round-trips correctly through that (signed->unsigned) cast.
POINTER_ID_MOUSE = -1

BLOB_MSG_TYPE_SCREEN_SHOT = 1
BLOB_MSG_TYPE_OPENCV_MAT = 2

_NAMED_KEYCODES = {
    "back": 4, "esc": 4, "home": 3, "enter": 66, "space": 62, "tab": 61,
    "menu": 82, "app_switch": 187,
    "up": 19, "down": 20, "left": 21, "right": 22, "dpad_center": 23,
    "volume_up": 24, "volume_down": 25, "power": 26,
}


def parse_size(s):
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT (e.g. 1200x2670), got {s!r}")


def android_keycode(name):
    """Map a pynput key name ('a', '5', 'up', 'enter', ...) to an Android keycode."""
    name = name.lower()
    if name in _NAMED_KEYCODES:
        return _NAMED_KEYCODES[name]
    if len(name) == 1:
        if "0" <= name <= "9":
            return 7 + (ord(name) - ord("0"))  # AKEYCODE_0 == 7
        if "a" <= name <= "z":
            return 29 + (ord(name) - ord("a"))  # AKEYCODE_A == 29
    return None


def keycode_message(action, keycode, meta_state=0):
    # matches ControlMessage::JsonDeserialize's expected shape
    # (src/message/control_msg.cpp) for CONTROL_MSG_TYPE_INJECT_KEYCODE
    return {
        "msg_type": "CONTROL_MSG_TYPE_INJECT_KEYCODE",
        "key_code": {"action": action, "key_code": keycode, "meta_state": meta_state},
    }


def touch_message(action, x, y, screen_width, screen_height,
                  pointer_id=POINTER_ID_MOUSE, pressure=1.0, buttons=0):
    # matches CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT's JSON shape. `x`/`y` are
    # pixel coordinates within a frame of size `screen_width` x
    # `screen_height` -- IMPORTANT: irobot_server's PositionMapper.map()
    # requires screen_width/screen_height to equal EXACTLY its real,
    # negotiated mirroring resolution (Size.equals(), not a ratio/scale) or
    # it silently drops the event. Callers must pass the real device
    # resolution here (see the comment above cmd_interactive), not the
    # dimensions of whatever smaller frame the coordinates were picked from.
    return {
        "msg_type": "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT",
        "touch_event": {
            "action": action,
            "buttons": buttons,
            "pointer": pointer_id,
            "pressure": pressure,
            "position": {
                "screen_size": {"width": screen_width, "height": screen_height},
                "point": {"x": x, "y": y},
            },
        },
    }


def send_json(sock, obj):
    # AgentController::ProcessMessages treats each recv() as one JSON
    # document (it doesn't do incremental/length-prefixed framing), so this
    # client always sends exactly one JSON object per socket write.
    sock.sendall(json.dumps(obj).encode("utf-8"))


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------

def cmd_record(args):
    # Keyboard capture uses pynput's global hook (background thread) so
    # every named key (arrows, enter, esc, ...) is available via
    # android_keycode(), same as before. Touch capture reuses the video
    # view + coordinate scaling from `interactive` (see the big comment
    # above cmd_interactive for why --screen-size is required). Both
    # mechanisms funnel into the same log_and_send() so everything ends up
    # in one timeline. Ctrl+C stops and saves, same as the keyboard-only
    # version did.
    import cv2
    import numpy as np
    from pynput import keyboard

    real_w, real_h = args.screen_size

    video_sock = socket.create_connection((args.host, args.port + 2))
    control_sock = socket.create_connection((args.host, args.port + 1))
    print(f"Connected to control port {args.port + 1} and video port {args.port + 2}.")
    print(f"Device screen size: {real_w}x{real_h}")
    print("Recording keyboard + touch (click/drag on the window)... Ctrl+C to stop.")

    events = []
    start = time.monotonic()

    def log_and_send(msg, label):
        msg = dict(msg)
        t_ms = int((time.monotonic() - start) * 1000)
        msg["t"] = t_ms
        try:
            send_json(control_sock, msg)
        except OSError as e:
            print(f"send failed: {e}")
            return
        # store the full message dict (+ "t") so this file uses the same
        # shape as irobot's own native recording (events.json, see below),
        # and `play` can replay either one interchangeably
        events.append(msg)
        print(f"[{t_ms:6d}ms] {label}")

    def handle_key(key, action):
        try:
            name = key.char
        except AttributeError:
            name = key.name  # e.g. Key.up -> "up"
        if name is None:
            return
        code = android_keycode(name)
        if code is None:
            return
        state = "DOWN" if action == ACTION_DOWN else "UP  "
        log_and_send(keycode_message(action, code), f"KEY  {state} {name} (keycode={code})")

    listener = keyboard.Listener(
        on_press=lambda k: handle_key(k, ACTION_DOWN),
        on_release=lambda k: handle_key(k, ACTION_UP),
    )
    listener.start()

    state = {"width": 0, "height": 0, "down": False}
    _ACTION_NAME = {MOTION_ACTION_DOWN: "DOWN", MOTION_ACTION_MOVE: "MOVE", MOTION_ACTION_UP: "UP  "}

    def send_touch(action, x, y):
        w, h = state["width"], state["height"]
        if not w or not h:
            return
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        rx = round(x / w * real_w)
        ry = round(y / h * real_h)
        buttons = BUTTON_PRIMARY if action != MOTION_ACTION_UP else 0
        msg = touch_message(action, rx, ry, real_w, real_h, buttons=buttons)
        log_and_send(msg, f"TOUCH {_ACTION_NAME[action]} ({rx},{ry})")

    def on_mouse(event, x, y, _flags, _userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["down"] = True
            send_touch(MOTION_ACTION_DOWN, x, y)
        elif event == cv2.EVENT_MOUSEMOVE and state["down"]:
            send_touch(MOTION_ACTION_MOVE, x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            state["down"] = False
            send_touch(MOTION_ACTION_UP, x, y)

    window = "irobot record"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    try:
        while True:
            msg_type, buffers = read_blob_message(video_sock)
            if msg_type != BLOB_MSG_TYPE_OPENCV_MAT or not buffers:
                continue
            width, height, pixels = buffers[0]
            state["width"], state["height"] = width, height
            frame = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width))
            cv2.imshow(window, frame)
            cv2.waitKey(1)  # pump the GUI event loop; keys are handled by pynput, not here
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        video_sock.close()
        control_sock.close()
        cv2.destroyAllWindows()

    with open(args.output, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Saved {len(events)} events to {args.output}")


# --------------------------------------------------------------------------
# play
# --------------------------------------------------------------------------
#
# `play` accepts two interchangeable file shapes, both a JSON array of
# per-event objects:
#
#  - this script's own `record` output: {"t": <ms>, "msg_type": ..., ...}
#    (covers both keyboard and touch, same as below)
#  - irobot's OWN native recording: irobot.exe can also record every touch
#    and key event it forwards to the device by itself, with no external
#    client needed -- press Ctrl+E to start, Ctrl+E again to stop (see
#    AgentManager::StartRecordEvents / ProcessKey in agent_manager.cpp).
#    It writes `events.json` in irobot's working directory, with each
#    event shaped by ControlMessage::JsonSerialize(): {"event_time":
#    "YYYY-MM-DD HH:MM:SS.mmm", "msg_type": ..., ...}.
#
# HISTORICAL NOTE (fixed server-side, keeping the filter anyway): older
# builds of ControlMessage::JsonSerialize() (src/message/control_msg.cpp)
# didn't implement every message type -- a recorded BACK_OR_SCREEN_ON/
# GET_CLIPBOARD/SET_CLIPBOARD event came out as {"event_time": "..."} with
# no "msg_type" key, and replaying that made JsonDeserialize() on the
# receiving end throw uncaught, crashing the whole irobot.exe process
# (thread had no try/catch). That's now fixed: JsonSerialize() always
# emits "msg_type", and JsonDeserialize() catches shape mismatches instead
# of letting them propagate. CONTROL_MSG_TYPE_UNKNOWN is still filtered
# out here, not because it's unsafe anymore, but because forwarding it is
# a pure no-op. START_RECORDING/END_RECORDING are filtered too, but for a
# different reason: AgentManager actually acts on them (they start/stop
# *another* events.json recording), which isn't what you want mid-playback.

_SAFE_TO_REPLAY = {
    "CONTROL_MSG_TYPE_INJECT_KEYCODE",
    "CONTROL_MSG_TYPE_INJECT_TEXT",
    "CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT",
    "CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT",
    "CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON",
    "CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL",
    "CONTROL_MSG_TYPE_COLLAPSE_NOTIFICATION_PANEL",
    "CONTROL_MSG_TYPE_ROTATE_DEVICE",
    "CONTROL_MSG_TYPE_GET_CLIPBOARD",
    "CONTROL_MSG_TYPE_SET_CLIPBOARD",
    "CONTROL_MSG_TYPE_SET_SCREEN_POWER_MODE",
}


def _event_time_ms(ev, first_event_time):
    if "t" in ev:
        return ev["t"]
    # native format: "YYYY-MM-DD HH:MM:SS.mmm"
    import datetime
    t = datetime.datetime.strptime(ev["event_time"], "%Y-%m-%d %H:%M:%S.%f")
    if first_event_time[0] is None:
        first_event_time[0] = t
    return (t - first_event_time[0]).total_seconds() * 1000.0


def cmd_play(args):
    with open(args.input) as f:
        events = json.load(f)

    skipped = 0
    first_event_time = [None]
    timed_events = []
    for ev in events:
        msg_type = ev.get("msg_type")
        if msg_type not in _SAFE_TO_REPLAY:
            skipped += 1
            continue
        timed_events.append((_event_time_ms(ev, first_event_time), ev))
    if skipped:
        print(f"Skipping {skipped} event(s) with no/unsafe msg_type (see script comments).")

    sock = socket.create_connection((args.host, args.port + 1))
    print(f"Connected to control port {args.port + 1}. Replaying {len(timed_events)} events.")

    t0 = time.monotonic()
    for t_ms, ev in timed_events:
        target = t0 + t_ms / 1000.0
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        send_json(sock, ev)
        # small gap so each message is very likely read in its own recv()
        # on the (currently non-length-prefixed) server side
        time.sleep(0.002)

    sock.close()
    print("Playback complete.")


# --------------------------------------------------------------------------
# stream
# --------------------------------------------------------------------------

BLOB_TYPE_NAMES = {0: "unknown", BLOB_MSG_TYPE_SCREEN_SHOT: "screen_shot", BLOB_MSG_TYPE_OPENCV_MAT: "opencv_mat"}


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("video socket closed")
        buf += chunk
    return bytes(buf)


def read_blob_message(sock):
    # BlobMessage::Serialize (src/message/blob_msg.cpp): a 40-byte
    # big-endian header (type, timestamp, id, count, total_length as u64),
    # then `count` buffers of [length:u64][width:u64][height:u64][pixels].
    header = recv_exact(sock, 40)
    msg_type, _timestamp, _msg_id, count, _total_length = struct.unpack(">QQQQQ", header)
    buffers = []
    for _ in range(count):
        length = struct.unpack(">Q", recv_exact(sock, 8))[0]
        payload = recv_exact(sock, 16 + length)
        width, height = struct.unpack(">QQ", payload[:16])
        pixels = payload[16:]
        buffers.append((width, height, pixels))
    return msg_type, buffers


def hamming(a, b):
    if len(a) != len(b):
        return -1
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


def cmd_stream(args):
    import cv2
    import numpy as np

    sock = socket.create_connection((args.host, args.port + 2))
    print(f"Connected to video port {args.port + 2}. Press 'q' in a video window to quit.")

    last_hash = {}
    try:
        while True:
            msg_type, buffers = read_blob_message(sock)
            if not buffers:
                continue
            width, height, pixels = buffers[0]
            channels = len(pixels) // (width * height)
            arr = np.frombuffer(pixels, dtype=np.uint8)
            frame = arr.reshape((height, width, channels)) if channels > 1 else arr.reshape((height, width))

            name = BLOB_TYPE_NAMES.get(msg_type, str(msg_type))
            if len(buffers) > 1:
                _, _, phash = buffers[1]
                dist = hamming(phash, last_hash.get(msg_type, phash))
                last_hash[msg_type] = phash
                if dist > 0:
                    print(f"{name}: frame changed (hamming distance={dist})")

            cv2.imshow(name, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        sock.close()
        cv2.destroyAllWindows()


# --------------------------------------------------------------------------
# interactive
# --------------------------------------------------------------------------
#
# Like `stream`, but the window is also a virtual touchscreen: clicking and
# dragging on it sends real CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT messages
# back to irobot, the same way clicking irobot's own SDL window does (see
# InputManager::ConvertMouseMotion / ConvertTouch in src/ui/input_manager.cpp).
# A handful of keys are forwarded too. Ctrl+Q quits (not 'q' alone, since a
# plain 'q' is a normal key you may want to send to the device).
#
# IMPORTANT: the touch event's "screen_size" is NOT just "whatever image
# we're showing". irobot_server's PositionMapper.map() (control/
# PositionMapper.java) requires it to equal EXACTLY the real negotiated
# mirroring resolution (Size.equals(), no tolerance) or it silently drops
# the event (verbose-only log, no error) -- so scaling anything by the
# small AI-agent thumbnail's own dimensions (the only size this client
# would otherwise know) never works. irobot itself prints that real
# resolution at startup: "Initial texture: WxH" (also "New texture: WxH"
# after a rotation/resize) -- pass it with --screen-size WxH, and this
# function scales thumbnail-space clicks up to that resolution before
# sending.

def _send_key(sock, name):
    code = android_keycode(name)
    if code is None:
        return
    send_json(sock, keycode_message(ACTION_DOWN, code))
    send_json(sock, keycode_message(ACTION_UP, code))


def cmd_interactive(args):
    import cv2
    import numpy as np

    real_w, real_h = args.screen_size

    video_sock = socket.create_connection((args.host, args.port + 2))
    control_sock = socket.create_connection((args.host, args.port + 1))
    print(f"Connected to video port {args.port + 2} and control port {args.port + 1}.")
    print(f"Device screen size: {real_w}x{real_h}")
    print("Click/drag on the window like a touchscreen. Esc = device BACK. Ctrl+Q to quit.")

    state = {"width": 0, "height": 0, "down": False}

    def send_touch(action, x, y):
        w, h = state["width"], state["height"]
        if not w or not h:
            return
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        # scale from the displayed thumbnail's pixel space to the real
        # device resolution -- see the module comment above cmd_interactive
        rx = round(x / w * real_w)
        ry = round(y / h * real_h)
        buttons = BUTTON_PRIMARY if action != MOTION_ACTION_UP else 0
        try:
            send_json(control_sock, touch_message(action, rx, ry, real_w, real_h, buttons=buttons))
        except OSError as e:
            print(f"send failed: {e}")

    def on_mouse(event, x, y, _flags, _userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["down"] = True
            send_touch(MOTION_ACTION_DOWN, x, y)
        elif event == cv2.EVENT_MOUSEMOVE and state["down"]:
            send_touch(MOTION_ACTION_MOVE, x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            state["down"] = False
            send_touch(MOTION_ACTION_UP, x, y)

    window = "irobot interactive"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    try:
        while True:
            msg_type, buffers = read_blob_message(video_sock)
            if msg_type != BLOB_MSG_TYPE_OPENCV_MAT or not buffers:
                continue  # skip the small screen_shot thumbnail + phash buffer
            width, height, pixels = buffers[0]
            state["width"], state["height"] = width, height
            frame = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width))
            cv2.imshow(window, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == 17:  # Ctrl+Q
                break
            elif key == 27:  # Esc -> device BACK (not a local quit key here)
                _send_key(control_sock, "back")
            elif 32 <= key < 127:
                _send_key(control_sock, chr(key))
    finally:
        video_sock.close()
        control_sock.close()
        cv2.destroyAllWindows()


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="irobot AI-agent test client")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="irobot's --port value (control=port+1, video=port+2)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_record = sub.add_parser("record", help="record keyboard + touch input and forward it live")
    p_record.add_argument("output", help="output JSON file")
    p_record.add_argument(
        "--screen-size", required=True, type=parse_size, metavar="WIDTHxHEIGHT",
        help="real device video resolution, exactly as irobot prints at startup "
             "(\"Initial texture: WxH\" / \"New texture: WxH\" after a rotation)")
    p_record.set_defaults(func=cmd_record)

    p_play = sub.add_parser("play", help="replay a recorded JSON event file")
    p_play.add_argument("input", help="input JSON file")
    p_play.set_defaults(func=cmd_play)

    p_stream = sub.add_parser("stream", help="display the live video/screenshot stream")
    p_stream.set_defaults(func=cmd_stream)

    p_interactive = sub.add_parser(
        "interactive", help="live view where clicking/dragging controls the device like a touchscreen")
    p_interactive.add_argument(
        "--screen-size", required=True, type=parse_size, metavar="WIDTHxHEIGHT",
        help="real device video resolution, exactly as irobot prints at startup "
             "(\"Initial texture: WxH\" / \"New texture: WxH\" after a rotation)")
    p_interactive.set_defaults(func=cmd_interactive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
