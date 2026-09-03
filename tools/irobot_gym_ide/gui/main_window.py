"""Main IDE window: project fields + action list (left dock), live-frame
canvas (center), event inspector for the selected action (right dock), and
a log panel (bottom of center) showing connection status, skipped/no-op
events from a live "Test" run, and validation warnings.

Click-to-test loop (see docs/irobot_gym_ide_design.md): select an action,
click Connect, click on the live frame to append events to it, click Test
to send the whole action to the real device and watch the canvas update
with the result -- calibration happens against the real device, not a
guessed screenshot, and you find out immediately whether a click landed on
the right button.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QLineEdit, QSpinBox, QPushButton, QLabel,
    QComboBox, QPlainTextEdit, QSplitter, QFileDialog, QMessageBox, QInputDialog,
    QCheckBox,
)
from PySide6.QtCore import Qt

from .. import io as project_io
from ..model import Project, Action, EventKind, PrimitiveEvent, conflicting_pointer_actions, orphan_releases
from ..connection import LiveConnection
from .canvas import CanvasView
from .inspector import ActionInspector

POLL_MS = 66  # ~15 fps canvas refresh; the video channel itself may deliver faster or slower


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("irobot Gym IDE")
        self.resize(1400, 900)

        self.project = Project(name="untitled")
        self.project_path: Path | None = None
        self.connection: LiveConnection | None = None
        self._selected_action: Action | None = None
        self._resolution_notice_shown = False  # reset per-connect, see _reconcile_detected_resolution
        # guards _sync_project_fields() while _load_project_into_fields() is
        # populating widgets one at a time -- without it, an early
        # setValue() (e.g. port) fires valueChanged, which reads back
        # widgets that haven't been set yet (e.g. reference height, still at
        # its old/default value) and clobbers self.project with them. This
        # was a real bug caught by a smoke test: opening a project silently
        # zeroed its reference resolution.
        self._loading_fields = False

        self._build_ui()
        self._refresh_action_list()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_frame)
        self._poll_timer.start(POLL_MS)

    # -- UI construction --------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()

        # left dock: project fields + action list
        left = QWidget()
        left_layout = QVBoxLayout(left)

        form = QFormLayout()
        self._name_edit = QLineEdit(self.project.name)
        self._package_edit = QLineEdit(self.project.package)
        self._serial_edit = QLineEdit(self.project.serial)
        self._host_edit = QLineEdit(self.project.host)
        self._port_spin = QSpinBox(); self._port_spin.setRange(1, 65535); self._port_spin.setValue(self.project.port)
        self._ref_w_spin = QSpinBox(); self._ref_w_spin.setRange(0, 10000); self._ref_w_spin.setValue(self.project.reference_width)
        self._ref_h_spin = QSpinBox(); self._ref_h_spin.setRange(0, 10000); self._ref_h_spin.setValue(self.project.reference_height)
        form.addRow("Name", self._name_edit)
        form.addRow("Package", self._package_edit)
        form.addRow("Device serial", self._serial_edit)
        form.addRow("Host", self._host_edit)
        form.addRow("Port", self._port_spin)
        form.addRow("Reference width", self._ref_w_spin)
        form.addRow("Reference height", self._ref_h_spin)
        for w in (self._name_edit, self._package_edit, self._serial_edit, self._host_edit):
            w.editingFinished.connect(self._sync_project_fields)
        for w in (self._port_spin, self._ref_w_spin, self._ref_h_spin):
            w.valueChanged.connect(self._sync_project_fields)
        left_layout.addLayout(form)

        self._detected_resolution_label = QLabel("Detected resolution: (connect to check)")
        left_layout.addWidget(self._detected_resolution_label)
        apply_resolution_btn = QPushButton("Apply Detected Resolution")
        apply_resolution_btn.clicked.connect(self._apply_detected_resolution)
        left_layout.addWidget(apply_resolution_btn)

        connect_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._toggle_connect)
        self._status_label = QLabel("disconnected")
        connect_row.addWidget(self._connect_btn)
        connect_row.addWidget(self._status_label)
        left_layout.addLayout(connect_row)

        left_layout.addWidget(QLabel("Actions"))
        self._action_list = QListWidget()
        self._action_list.currentItemChanged.connect(self._on_action_selected)
        left_layout.addWidget(self._action_list)

        action_btn_row = QHBoxLayout()
        add_action_btn = QPushButton("Add Action")
        remove_action_btn = QPushButton("Remove Action")
        add_action_btn.clicked.connect(self._add_action)
        remove_action_btn.clicked.connect(self._remove_action)
        action_btn_row.addWidget(add_action_btn)
        action_btn_row.addWidget(remove_action_btn)
        left_layout.addLayout(action_btn_row)

        left_layout.addWidget(QLabel("New event on canvas click:"))
        click_row = QHBoxLayout()
        self._new_kind_combo = QComboBox()
        self._new_kind_combo.addItems([EventKind.TAP.value, EventKind.PRESS.value, EventKind.MOVE.value])
        self._new_pointer_spin = QSpinBox(); self._new_pointer_spin.setRange(0, 9)
        click_row.addWidget(self._new_kind_combo)
        click_row.addWidget(self._new_pointer_spin)
        left_layout.addLayout(click_row)

        self._live_send_checkbox = QCheckBox("Send new events live as you click (recommended)")
        self._live_send_checkbox.setChecked(True)
        left_layout.addWidget(self._live_send_checkbox)

        test_btn = QPushButton("Test Action (send live)")
        test_btn.clicked.connect(self._test_action)
        left_layout.addWidget(test_btn)
        release_btn = QPushButton("Release All Held Pointers")
        release_btn.clicked.connect(self._release_all)
        left_layout.addWidget(release_btn)

        left_dock = QDockWidget("Project", self)
        left_dock.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)

        # right dock: inspector
        self._inspector = ActionInspector()
        self._inspector.actionChanged.connect(self._on_action_edited)
        right_dock = QDockWidget("Action events", self)
        right_dock.setWidget(self._inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)

        # center: canvas over log
        self._canvas = CanvasView()
        self._canvas.pointClicked.connect(self._on_canvas_clicked)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._canvas)
        splitter.addWidget(self._log)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        menu.addAction("New Project", self._new_project)
        menu.addAction("Open Project...", self._open_project)
        menu.addAction("Save Project", self._save_project)
        menu.addAction("Save Project As...", self._save_project_as)

    # -- logging --------------------------------------------------------

    def _log_line(self, text: str) -> None:
        self._log.appendPlainText(text)

    # -- project fields --------------------------------------------------------

    def _sync_project_fields(self) -> None:
        if self._loading_fields:
            return
        self.project.name = self._name_edit.text()
        self.project.package = self._package_edit.text()
        self.project.serial = self._serial_edit.text()
        self.project.host = self._host_edit.text()
        self.project.port = self._port_spin.value()
        self.project.reference_width = self._ref_w_spin.value()
        self.project.reference_height = self._ref_h_spin.value()
        self.setWindowTitle(f"irobot Gym IDE - {self.project.name}")

    def _load_project_into_fields(self) -> None:
        self._loading_fields = True
        try:
            self._name_edit.setText(self.project.name)
            self._package_edit.setText(self.project.package)
            self._serial_edit.setText(self.project.serial)
            self._host_edit.setText(self.project.host)
            self._port_spin.setValue(self.project.port)
            self._ref_w_spin.setValue(self.project.reference_width)
            self._ref_h_spin.setValue(self.project.reference_height)
        finally:
            self._loading_fields = False
        self.setWindowTitle(f"irobot Gym IDE - {self.project.name}")

    # -- project file menu actions --------------------------------------------------------

    def _new_project(self) -> None:
        self.project = Project(name="untitled")
        self.project_path = None
        self._selected_action = None
        self._load_project_into_fields()
        self._refresh_action_list()
        self._inspector.set_action(None)

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            self.project = project_io.load_project(path)
        except Exception as e:  # noqa: BLE001 -- surfaced to the user, not swallowed
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self.project_path = Path(path)
        self._load_project_into_fields()
        self._refresh_action_list()
        self._inspector.set_action(None)
        self._log_line(f"Opened {path}")
        self._warn_pointer_conflicts()

    def _save_project(self) -> None:
        if self.project_path is None:
            self._save_project_as()
            return
        project_io.save_project(self.project, self.project_path)
        self._log_line(f"Saved {self.project_path}")

    def _save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", f"{self.project.name}.yaml", "YAML (*.yaml)")
        if not path:
            return
        self.project_path = Path(path)
        project_io.save_project(self.project, self.project_path)
        self._log_line(f"Saved {self.project_path}")

    # -- actions --------------------------------------------------------

    def _refresh_action_list(self) -> None:
        self._action_list.clear()
        for name in self.project.actions:
            self._action_list.addItem(QListWidgetItem(name))

    def _add_action(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Action", "Action name:")
        if not ok or not name:
            return
        if name in self.project.actions:
            QMessageBox.warning(self, "Add Action", f"Action {name!r} already exists.")
            return
        self.project.add_action(Action(name=name))
        self._refresh_action_list()
        self._warn_pointer_conflicts()

    def _remove_action(self) -> None:
        item = self._action_list.currentItem()
        if item is None:
            return
        self.project.remove_action(item.text())
        self._refresh_action_list()
        self._inspector.set_action(None)
        self._selected_action = None

    def _on_action_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._selected_action = None
            self._inspector.set_action(None)
            return
        self._selected_action = self.project.actions.get(current.text())
        self._inspector.set_action(self._selected_action)

    def _on_action_edited(self) -> None:
        self._warn_pointer_conflicts()

    def _warn_pointer_conflicts(self) -> None:
        conflicts = conflicting_pointer_actions(self.project.actions)
        for pointer_id, names in conflicts:
            self._log_line(
                f"Note: pointer {pointer_id} is left held by more than one action ({', '.join(names)}) -- "
                f"fine if these are meant as mutually-exclusive holds sharing one thumb (see plan §7.4), "
                f"otherwise check for a missing RELEASE.")
        for action_name, pointer_id in orphan_releases(self.project.actions):
            self._log_line(
                f"Warning: action {action_name!r} releases pointer {pointer_id}, but no action in this "
                f"project ever presses that pointer -- likely a typo'd pointer_id.")

    # -- connection --------------------------------------------------------

    def _toggle_connect(self) -> None:
        if self.connection is not None and self.connection.connected:
            self.connection.disconnect()
            self.connection = None
            self._status_label.setText("disconnected")
            self._connect_btn.setText("Connect")
            self._detected_resolution_label.setText("Detected resolution: (connect to check)")
            self._log_line("Disconnected.")
            return
        self._sync_project_fields()
        self.connection = LiveConnection(self.project.host, self.project.port)
        try:
            self.connection.connect()
        except OSError as e:
            QMessageBox.critical(self, "Connect failed", str(e))
            self.connection = None
            return
        self._status_label.setText(f"connected to {self.project.host}:{self.project.port}")
        self._connect_btn.setText("Disconnect")
        self._log_line(f"Connected to {self.project.host}:{self.project.port}.")
        self._resolution_notice_shown = False

    # -- canvas / live loop --------------------------------------------------------

    def _poll_frame(self) -> None:
        if self.connection is None or not self.connection.connected:
            return
        self._reconcile_detected_resolution()
        frame = self.connection.latest_frame()
        if frame is None:
            return
        width, height, ndarray = frame
        self._canvas.update_frame(width, height, ndarray)
        self._canvas.set_markers(self._markers_for_selected_action(width, height))

    def _reconcile_detected_resolution(self) -> None:
        """Compares irobot's self-reported real resolution (BLOB_MSG_TYPE_RESOLUTION,
        requires the AgentManager::SendResolution build from this session) against
        the project's Reference width/height, which is what's actually used when
        sending touch events (see _require_reference_resolution). Auto-fills an
        unset value; never silently overwrites an already-set one that differs,
        since every stored event (x, y) is meaningful only relative to whatever
        reference resolution was in effect when it was placed -- changing it out
        from under existing events would silently invalidate their coordinates."""
        detected = self.connection.latest_resolution()
        if detected is None:
            return  # irobot build predates this message, or none received yet
        dw, dh = detected
        self._detected_resolution_label.setText(f"Detected resolution: {dw}x{dh}")

        ref_w, ref_h = self.project.reference_width, self.project.reference_height
        if not ref_w or not ref_h:
            self._loading_fields = True
            try:
                self._ref_w_spin.setValue(dw)
                self._ref_h_spin.setValue(dh)
            finally:
                self._loading_fields = False
            self.project.reference_width, self.project.reference_height = dw, dh
            self._log_line(f"Auto-detected resolution {dw}x{dh} from device; applied to Reference width/height.")
            self._resolution_notice_shown = True
        elif (ref_w, ref_h) != (dw, dh):
            if not self._resolution_notice_shown:
                self._log_line(
                    f"MISMATCH: project Reference width/height is {ref_w}x{ref_h}, but the device reports "
                    f"{dw}x{dh}. Every touch event sent with the wrong value is silently dropped by the "
                    f"device -- click 'Apply Detected Resolution' to fix it (existing event coordinates "
                    f"stay numerically the same, so re-check placements against the canvas after applying).")
                self._resolution_notice_shown = True
        elif not self._resolution_notice_shown:
            self._log_line(f"Reference resolution {ref_w}x{ref_h} confirmed to match the device.")
            self._resolution_notice_shown = True

    def _apply_detected_resolution(self) -> None:
        if self.connection is None or not self.connection.connected:
            self._log_line("Apply Detected Resolution ignored: not connected.")
            return
        detected = self.connection.latest_resolution()
        if detected is None:
            self._log_line(
                "Apply Detected Resolution ignored: no BLOB_MSG_TYPE_RESOLUTION received yet -- either "
                "irobot hasn't sent one (older build predating this feature) or no frame has arrived yet.")
            return
        dw, dh = detected
        self._loading_fields = True
        try:
            self._ref_w_spin.setValue(dw)
            self._ref_h_spin.setValue(dh)
        finally:
            self._loading_fields = False
        self.project.reference_width, self.project.reference_height = dw, dh
        self._log_line(f"Applied detected resolution {dw}x{dh} to Reference width/height.")
        self._resolution_notice_shown = True

    def _markers_for_selected_action(self, frame_w: int, frame_h: int):
        if self._selected_action is None:
            return []
        markers = []
        for i, event in enumerate(self._selected_action.events):
            if event.x is None or event.y is None:
                continue
            fx, fy = self._reference_to_frame(event.x, event.y, frame_w, frame_h)
            markers.append((fx, fy, event.pointer_id, f"{i}:{event.kind.value}"))
        return markers

    def _reference_to_frame(self, x: int, y: int, frame_w: int, frame_h: int):
        ref_w, ref_h = self.project.reference_width, self.project.reference_height
        if not ref_w or not ref_h:
            return x, y  # no calibration yet -- treat frame space and reference space as the same
        return round(x / ref_w * frame_w), round(y / ref_h * frame_h)

    def _frame_to_reference(self, x: int, y: int, frame_w: int, frame_h: int):
        ref_w, ref_h = self.project.reference_width, self.project.reference_height
        if not ref_w or not ref_h:
            return x, y
        return round(x / frame_w * ref_w), round(y / frame_h * ref_h)

    def _require_reference_resolution(self):
        """Returns (ref_w, ref_h) only if both are actually set -- never a
        guessed fallback. irobot_server's PositionMapper.map() requires a
        touch event's screen_size to equal the real negotiated device
        resolution EXACTLY (Size.equals(), no tolerance); the video frame
        this tool displays is always a downscaled copy (<=800px, see
        AgentManager::SendOpenCVImage), so sending with the frame's own
        dimensions is not an approximation, it is a guaranteed mismatch --
        the server drops the event with a verbose-only log line and no
        visible error, which reads as "nothing happened." An earlier version
        of this tool fell back to the frame's dimensions here, which is
        exactly why testing an action appeared to have no effect."""
        ref_w, ref_h = self.project.reference_width, self.project.reference_height
        if not ref_w or not ref_h:
            self._log_line(
                "BLOCKED: Reference width/height is not set. Every touch event's screen_size must "
                "exactly match irobot's real device resolution or the device silently drops it -- "
                "this is why nothing appeared to happen. Read the real resolution from irobot's own "
                "startup log (\"Initial texture: WxH\", also printed as \"New texture: WxH\" after a "
                "rotation) and set Reference width/height in the left panel to that exact value.")
            return None
        return ref_w, ref_h

    def _on_canvas_clicked(self, x: int, y: int) -> None:
        if self._selected_action is None:
            self._log_line("Click ignored: no action selected.")
            return
        if self.connection is None:
            self._log_line("Click ignored: connect first so frame dimensions are known.")
            return
        frame = self.connection.latest_frame()
        if frame is None:
            return
        frame_w, frame_h = frame[0], frame[1]
        if not self.project.reference_width or not self.project.reference_height:
            self._log_line(
                "Warning: reference resolution is not set -- storing raw frame-pixel coordinates, "
                "and this click will NOT be sent live even if the checkbox below is on (sending now "
                "would use the wrong screen_size and be silently dropped by the device). Set "
                "Reference width/height first -- see irobot's startup log \"Initial texture: WxH\".")
        rx, ry = self._frame_to_reference(x, y, frame_w, frame_h)
        kind = EventKind(self._new_kind_combo.currentText())
        pointer_id = self._new_pointer_spin.value()
        event = self._inspector.add_event_at_point(rx, ry, kind, pointer_id)
        self._log_line(f"Added {kind.value} @ ({rx},{ry}) pointer={pointer_id} to {self._selected_action.name}")

        if event is None or not self._live_send_checkbox.isChecked():
            return
        ref = self._require_reference_resolution()
        if ref is None:
            return  # already logged; the "Warning" above already told the user why
        reason = self.connection.send_primitive(event, *ref)
        if reason is None:
            self._log_line(f"  -> sent live ({event.kind.value} pointer={event.pointer_id}).")
        else:
            self._log_line(f"  -> NOT sent: {reason}")

    # -- test / release --------------------------------------------------------

    def _test_action(self) -> None:
        if self._selected_action is None:
            self._log_line("Test ignored: no action selected.")
            return
        if self.connection is None or not self.connection.connected:
            self._log_line("Test ignored: not connected.")
            return
        ref = self._require_reference_resolution()
        if ref is None:
            return
        skipped = self.connection.run_action(self._selected_action, *ref)
        self._log_line(f"Sent action {self._selected_action.name!r} ({len(self._selected_action.events)} events).")
        for i, reason in skipped:
            self._log_line(f"  event {i} skipped: {reason}")

    def _release_all(self) -> None:
        if self.connection is None or not self.connection.connected:
            return
        ref = self._require_reference_resolution()
        if ref is None:
            return
        self.connection.release_all_held(*ref)
        self._log_line("Released all held pointers.")

    def closeEvent(self, event) -> None:
        if self.connection is not None:
            self.connection.disconnect()
        super().closeEvent(event)
