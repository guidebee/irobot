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

import base64
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, QLabel,
    QComboBox, QPlainTextEdit, QSplitter, QFileDialog, QMessageBox, QInputDialog,
    QCheckBox, QTabWidget, QAbstractItemView,
)
from PySide6.QtCore import Qt

from .. import io as project_io
from ..model import (
    Project, Action, EventKind, GameplaySession, GameRun, HudRegion, HudRegionCombo, ImageTemplate, PrimitiveEvent,
    conflicting_pointer_actions, orphan_releases,
)
from ..connection import LiveConnection
from ..device_recorder import DeviceEventRecorder, merge_gestures_into_events, segment_into_gestures
from ..hud_classifier import classify_session
from ..run_engine import GameRunExecutor
from ..session_replay import SessionPlayer
from .canvas import CanvasView
from .inspector import ActionInspector
from .run_editor import RunEditorWidget

POLL_MS = 66  # ~15 fps canvas refresh; the video channel itself may deliver faster or slower


class _RunSignals(QObject):
    """GameRunExecutor.run() executes on a worker thread (see MainWindow's
    _run_game_run); Qt signals are the one thread-safe way to get its log
    lines and completion back onto the GUI thread -- a queued connection is
    automatic whenever emitter and receiver live on different threads."""
    logLine = Signal(str)
    finished = Signal()


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
        self._device_recorder: DeviceEventRecorder | None = None
        self._device_recording_axis_ranges = None
        self._device_recording_rotation = 0
        self._session_recorder: DeviceEventRecorder | None = None
        self._session_recording_axis_ranges = None
        self._session_recording_rotation = 0
        self._session_player: SessionPlayer | None = None
        self._session_signals = _RunSignals()
        self._session_signals.logLine.connect(lambda text: self._log_line(text))
        self._selected_run: GameRun | None = None
        self._selected_template: ImageTemplate | None = None
        self._loading_template_fields = False   # same guard purpose as _loading_fields, for the template props row
        self._selected_hud_region: HudRegion | None = None
        self._loading_hud_region_fields = False   # same guard purpose as _loading_template_fields
        self._selected_combo: HudRegionCombo | None = None
        self._loading_combo_fields = False   # same guard purpose as _loading_hud_region_fields
        self._capture_target = "template"   # "template" or "hud_region" -- which capture button is armed;
                                              # the canvas only has one capture mode, see _on_region_selected
        self._run_executor: GameRunExecutor | None = None
        self._run_signals = _RunSignals()
        self._run_signals.logLine.connect(lambda text: self._run_editor.log_line(text))
        self._run_signals.finished.connect(self._on_run_finished)
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

        left_layout.addWidget(QLabel("Record real touches directly on the device (bypasses the mirror):"))
        self._record_device_btn = QPushButton("Record from Device")
        self._record_device_btn.clicked.connect(self._toggle_device_recording)
        left_layout.addWidget(self._record_device_btn)

        left_layout.addWidget(QLabel(
            "Gameplay Sessions (record a whole playthrough as raw events, for later\n"
            "classification into actions -- see recordings/*.session.yaml):"))
        self._record_session_btn = QPushButton("Record Gameplay Session")
        self._record_session_btn.clicked.connect(self._toggle_session_recording)
        left_layout.addWidget(self._record_session_btn)
        self._session_list = QListWidget()
        left_layout.addWidget(self._session_list)
        session_btn_row = QHBoxLayout()
        classify_session_btn = QPushButton("Classify Session")
        classify_session_btn.clicked.connect(self._classify_session)
        replay_raw_btn = QPushButton("Replay Raw")
        replay_raw_btn.clicked.connect(self._replay_session_raw)
        replay_classified_btn = QPushButton("Replay Classified")
        replay_classified_btn.clicked.connect(self._replay_session_classified)
        stop_replay_btn = QPushButton("Stop Replay")
        stop_replay_btn.clicked.connect(self._stop_session_replay)
        session_btn_row.addWidget(classify_session_btn)
        session_btn_row.addWidget(replay_raw_btn)
        session_btn_row.addWidget(replay_classified_btn)
        session_btn_row.addWidget(stop_replay_btn)
        left_layout.addLayout(session_btn_row)

        left_layout.addWidget(QLabel("Game Runs"))
        self._run_list = QListWidget()
        self._run_list.currentItemChanged.connect(self._on_run_selected)
        left_layout.addWidget(self._run_list)

        run_btn_row = QHBoxLayout()
        add_run_btn = QPushButton("Add Run")
        remove_run_btn = QPushButton("Remove Run")
        add_run_btn.clicked.connect(self._add_run)
        remove_run_btn.clicked.connect(self._remove_run)
        run_btn_row.addWidget(add_run_btn)
        run_btn_row.addWidget(remove_run_btn)
        left_layout.addLayout(run_btn_row)

        left_layout.addWidget(QLabel("Image Templates (for Game Run Compare / Find Template nodes)"))
        self._template_list = QListWidget()
        self._template_list.currentItemChanged.connect(self._on_template_selected)
        left_layout.addWidget(self._template_list)

        self._template_preview = QLabel()
        self._template_preview.setFixedHeight(60)
        self._template_preview.setAlignment(Qt.AlignCenter)
        self._template_preview.setStyleSheet("border: 1px solid #888;")
        left_layout.addWidget(self._template_preview)

        template_threshold_row = QHBoxLayout()
        template_threshold_row.addWidget(QLabel("Match threshold"))
        self._template_threshold_spin = QDoubleSpinBox()
        self._template_threshold_spin.setRange(0.0, 1.0)
        self._template_threshold_spin.setSingleStep(0.01)
        self._template_threshold_spin.setDecimals(2)
        self._template_threshold_spin.valueChanged.connect(self._on_template_threshold_changed)
        template_threshold_row.addWidget(self._template_threshold_spin)
        template_threshold_row.addStretch(1)
        left_layout.addLayout(template_threshold_row)

        template_btn_row = QHBoxLayout()
        self._capture_region_btn = QPushButton("Capture Region")
        self._capture_region_btn.setCheckable(True)
        self._capture_region_btn.toggled.connect(self._toggle_capture_mode)
        remove_template_btn = QPushButton("Remove Template")
        remove_template_btn.clicked.connect(self._remove_template)
        template_btn_row.addWidget(self._capture_region_btn)
        template_btn_row.addWidget(remove_template_btn)
        left_layout.addLayout(template_btn_row)

        left_layout.addWidget(QLabel(
            "HUD Regions (fixed on-screen buttons -- classifies a gameplay session's\n"
            "gestures by where they landed; see hud_classifier.py):"))
        self._hud_region_list = QListWidget()
        self._hud_region_list.currentItemChanged.connect(self._on_hud_region_selected)
        left_layout.addWidget(self._hud_region_list)

        hud_region_action_row = QHBoxLayout()
        hud_region_action_row.addWidget(QLabel("Action name"))
        self._hud_region_action_edit = QLineEdit()
        self._hud_region_action_edit.editingFinished.connect(self._on_hud_region_action_edited)
        hud_region_action_row.addWidget(self._hud_region_action_edit)
        left_layout.addLayout(hud_region_action_row)

        hud_region_btn_row = QHBoxLayout()
        self._capture_hud_region_btn = QPushButton("Capture HUD Region")
        self._capture_hud_region_btn.setCheckable(True)
        self._capture_hud_region_btn.toggled.connect(self._toggle_hud_capture_mode)
        remove_hud_region_btn = QPushButton("Remove HUD Region")
        remove_hud_region_btn.clicked.connect(self._remove_hud_region)
        hud_region_btn_row.addWidget(self._capture_hud_region_btn)
        hud_region_btn_row.addWidget(remove_hud_region_btn)
        left_layout.addLayout(hud_region_btn_row)

        left_layout.addWidget(QLabel(
            "HUD Combos (2+ regions touched together -> one action, e.g.\n"
            "right_button + jump_button -> right_jump):"))
        self._combo_list = QListWidget()
        self._combo_list.currentItemChanged.connect(self._on_combo_selected)
        left_layout.addWidget(self._combo_list)

        left_layout.addWidget(QLabel("Regions in combo (ctrl/shift-click to select 2+):"))
        self._combo_regions_list = QListWidget()
        self._combo_regions_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._combo_regions_list.itemSelectionChanged.connect(self._on_combo_regions_changed)
        left_layout.addWidget(self._combo_regions_list)

        combo_action_row = QHBoxLayout()
        combo_action_row.addWidget(QLabel("Action name"))
        self._combo_action_edit = QLineEdit()
        self._combo_action_edit.editingFinished.connect(self._on_combo_action_edited)
        combo_action_row.addWidget(self._combo_action_edit)
        left_layout.addLayout(combo_action_row)

        combo_btn_row = QHBoxLayout()
        add_combo_btn = QPushButton("Add Combo")
        add_combo_btn.clicked.connect(self._add_hud_combo)
        remove_combo_btn = QPushButton("Remove Combo")
        remove_combo_btn.clicked.connect(self._remove_hud_combo)
        combo_btn_row.addWidget(add_combo_btn)
        combo_btn_row.addWidget(remove_combo_btn)
        left_layout.addLayout(combo_btn_row)

        left_dock = QDockWidget("Project", self)
        left_dock.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)

        # right dock: inspector
        self._inspector = ActionInspector()
        self._inspector.actionChanged.connect(self._on_action_edited)
        right_dock = QDockWidget("Action events", self)
        right_dock.setWidget(self._inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)

        # center: tabbed -- live mirror/canvas+log, and the game-run node graph editor
        self._canvas = CanvasView()
        self._canvas.pointClicked.connect(self._on_canvas_clicked)
        self._canvas.regionSelected.connect(self._on_region_selected)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._canvas)
        splitter.addWidget(self._log)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        self._run_editor = RunEditorWidget(
            get_action_names=lambda: list(self.project.actions.keys()),
            get_template_names=lambda: list(self.project.templates.keys()))
        self._run_editor.graphChanged.connect(self._on_run_graph_changed)
        self._run_editor.runRequested.connect(self._run_game_run)
        self._run_editor.stopRequested.connect(self._stop_game_run)

        tabs = QTabWidget()
        tabs.addTab(splitter, "Mirror / Actions")
        tabs.addTab(self._run_editor, "Game Run")
        self.setCentralWidget(tabs)

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
        self._selected_run = None
        self._selected_template = None
        self._selected_hud_region = None
        self._selected_combo = None
        self._load_project_into_fields()
        self._refresh_action_list()
        self._refresh_run_list()
        self._refresh_template_list()
        self._refresh_hud_region_list()
        self._refresh_combo_list()
        self._refresh_session_list()
        self._inspector.set_action(None)
        self._run_editor.set_run(None)

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
        self._selected_run = None
        self._selected_template = None
        self._selected_hud_region = None
        self._selected_combo = None
        self._load_project_into_fields()
        self._refresh_action_list()
        self._refresh_run_list()
        self._refresh_template_list()
        self._refresh_hud_region_list()
        self._refresh_combo_list()
        self._refresh_session_list()
        self._inspector.set_action(None)
        self._run_editor.set_run(None)
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
        self._refresh_session_list()
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
        self._on_run_graph_changed()

    def _remove_action(self) -> None:
        item = self._action_list.currentItem()
        if item is None:
            return
        self.project.remove_action(item.text())
        self._refresh_action_list()
        self._inspector.set_action(None)
        self._selected_action = None
        self._on_run_graph_changed()

    def _on_action_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._selected_action = None
            self._inspector.set_action(None)
            return
        self._selected_action = self.project.actions.get(current.text())
        self._inspector.set_action(self._selected_action)

    def _on_action_edited(self) -> None:
        self._warn_pointer_conflicts()

    # -- game runs --------------------------------------------------------

    def _refresh_run_list(self) -> None:
        self._run_list.clear()
        for name in self.project.runs:
            self._run_list.addItem(QListWidgetItem(name))

    def _add_run(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Game Run", "Run name:")
        if not ok or not name:
            return
        if name in self.project.runs:
            QMessageBox.warning(self, "Add Game Run", f"Run {name!r} already exists.")
            return
        self.project.add_run(GameRun(name=name))
        self._refresh_run_list()

    def _remove_run(self) -> None:
        item = self._run_list.currentItem()
        if item is None:
            return
        self.project.remove_run(item.text())
        self._refresh_run_list()
        self._run_editor.set_run(None)
        self._selected_run = None

    def _on_run_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._selected_run = None
            self._run_editor.set_run(None)
            return
        self._selected_run = self.project.runs.get(current.text())
        self._run_editor.set_run(self._selected_run)
        self._on_run_graph_changed()

    def _on_run_graph_changed(self) -> None:
        self._run_editor.refresh_warnings(self.project.actions, self.project.templates)

    def _run_game_run(self, game_run: GameRun | None) -> None:
        if game_run is None:
            return
        if self.connection is None or not self.connection.connected:
            self._run_editor.log_line("Run ignored: not connected.")
            return
        ref = self._require_reference_resolution()
        if ref is None:
            return
        ref_w, ref_h = ref
        self._run_executor = GameRunExecutor(
            self.connection, self.project.actions, ref_w, ref_h,
            on_log=self._run_signals.logLine.emit, templates=self.project.templates)
        self._run_editor.set_running(True)
        self._run_editor.log_line(f"Running {game_run.name!r}...")

        def worker() -> None:
            try:
                self._run_executor.run(game_run)
            finally:
                self._run_signals.finished.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _stop_game_run(self) -> None:
        if self._run_executor is not None:
            self._run_executor.stop()
            self._run_editor.log_line("Stop requested.")

    def _on_run_finished(self) -> None:
        self._run_editor.set_running(False)
        self._run_editor.log_line("Run finished.")

    # -- compare templates --------------------------------------------------------

    def _refresh_template_list(self) -> None:
        self._template_list.clear()
        for name in self.project.templates:
            self._template_list.addItem(QListWidgetItem(name))

    def _on_template_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._selected_template = None
        else:
            self._selected_template = self.project.templates.get(current.text())
        self._update_template_props()

    def _update_template_props(self) -> None:
        template = self._selected_template
        self._loading_template_fields = True
        try:
            self._template_threshold_spin.setValue(template.threshold if template else 0.9)
        finally:
            self._loading_template_fields = False
        if template is not None and template.pixels_b64 and template.image_w and template.image_h:
            raw = base64.b64decode(template.pixels_b64)
            image = QImage(raw, template.image_w, template.image_h, template.image_w, QImage.Format_Grayscale8)
            self._template_preview.setPixmap(
                QPixmap.fromImage(image).scaledToHeight(60, Qt.SmoothTransformation))
        else:
            self._template_preview.clear()

    def _on_template_threshold_changed(self, value: float) -> None:
        if self._loading_template_fields or self._selected_template is None:
            return
        self._selected_template.threshold = value

    def _remove_template(self) -> None:
        item = self._template_list.currentItem()
        if item is None:
            return
        self.project.remove_template(item.text())
        self._selected_template = None
        self._refresh_template_list()
        self._update_template_props()
        self._on_run_graph_changed()

    def _toggle_capture_mode(self, enabled: bool) -> None:
        if enabled:
            self._capture_target = "template"
            self._capture_hud_region_btn.setChecked(False)   # mutually exclusive -- canvas has one capture mode
        self._canvas.set_capture_mode(enabled)
        self._capture_region_btn.setText("Click-drag on the frame to select..." if enabled else "Capture Region")

    def _on_region_selected(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self._capture_target == "hud_region":
            self._capture_hud_region_btn.setChecked(False)   # one-shot, same as template capture below
            self._capture_hud_region(x0, y0, x1, y1)
        else:
            self._capture_region_btn.setChecked(False)
            self._capture_template_region(x0, y0, x1, y1)

    def _capture_template_region(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self.connection is None:
            self._log_line("Capture ignored: connect first so a live frame is available.")
            return
        frame = self.connection.latest_frame()
        if frame is None:
            self._log_line("Capture ignored: no frame received yet.")
            return
        frame_w, frame_h, frame_arr = frame
        ref = self._require_reference_resolution()
        if ref is None:
            return  # already logged why
        ref_w, ref_h = ref
        rx0, ry0 = self._frame_to_reference(x0, y0, frame_w, frame_h)
        rx1, ry1 = self._frame_to_reference(x1, y1, frame_w, frame_h)
        rw, rh = max(1, rx1 - rx0), max(1, ry1 - ry0)

        name, ok = QInputDialog.getText(self, "Capture Template", "Template name:")
        if not ok or not name:
            self._log_line("Capture discarded (no name given).")
            return
        if name in self.project.templates:
            QMessageBox.warning(self, "Capture Region", f"Template {name!r} already exists.")
            return

        template = ImageTemplate.capture(name, rx0, ry0, rw, rh, frame_w, frame_h, frame_arr, ref_w, ref_h)
        self.project.add_template(template)
        self._refresh_template_list()
        self._on_run_graph_changed()
        self._log_line(f"Captured template {name!r}: region ({rx0},{ry0}) {rw}x{rh} (reference space), "
                        f"{template.image_w}x{template.image_h}px.")

    # -- HUD regions --------------------------------------------------------

    def _refresh_hud_region_list(self) -> None:
        self._hud_region_list.clear()
        for name in self.project.hud_regions:
            self._hud_region_list.addItem(QListWidgetItem(name))
        self._refresh_combo_region_choices()

    def _on_hud_region_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._selected_hud_region = None
        else:
            self._selected_hud_region = self.project.hud_regions.get(current.text())
        self._loading_hud_region_fields = True
        try:
            self._hud_region_action_edit.setText(
                self._selected_hud_region.action_name if self._selected_hud_region else "")
        finally:
            self._loading_hud_region_fields = False

    def _on_hud_region_action_edited(self) -> None:
        if self._loading_hud_region_fields or self._selected_hud_region is None:
            return
        self._selected_hud_region.action_name = self._hud_region_action_edit.text()

    def _remove_hud_region(self) -> None:
        item = self._hud_region_list.currentItem()
        if item is None:
            return
        self.project.remove_hud_region(item.text())
        self._selected_hud_region = None
        self._refresh_hud_region_list()
        self._hud_region_action_edit.clear()

    def _toggle_hud_capture_mode(self, enabled: bool) -> None:
        if enabled:
            self._capture_target = "hud_region"
            self._capture_region_btn.setChecked(False)   # mutually exclusive -- canvas has one capture mode
        self._canvas.set_capture_mode(enabled)
        self._capture_hud_region_btn.setText(
            "Click-drag on the frame to select..." if enabled else "Capture HUD Region")

    def _capture_hud_region(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self.connection is None:
            self._log_line("Capture ignored: connect first so a live frame is available.")
            return
        frame = self.connection.latest_frame()
        if frame is None:
            self._log_line("Capture ignored: no frame received yet.")
            return
        frame_w, frame_h, _frame_arr = frame
        ref = self._require_reference_resolution()
        if ref is None:
            return  # already logged why
        rx0, ry0 = self._frame_to_reference(x0, y0, frame_w, frame_h)
        rx1, ry1 = self._frame_to_reference(x1, y1, frame_w, frame_h)
        rw, rh = max(1, rx1 - rx0), max(1, ry1 - ry0)

        name, ok = QInputDialog.getText(self, "Capture HUD Region", "Region name:")
        if not ok or not name:
            self._log_line("Capture discarded (no name given).")
            return
        if name in self.project.hud_regions:
            QMessageBox.warning(self, "Capture HUD Region", f"HUD region {name!r} already exists.")
            return

        region = HudRegion(name=name, x=rx0, y=ry0, width=rw, height=rh)
        self.project.add_hud_region(region)
        self._refresh_hud_region_list()
        self._log_line(f"Captured HUD region {name!r}: ({rx0},{ry0}) {rw}x{rh} (reference space) -- "
                        f"set its Action name, then use Classify Session.")

    # -- HUD combos --------------------------------------------------------

    def _refresh_combo_list(self) -> None:
        self._combo_list.clear()
        for name in self.project.hud_region_combos:
            self._combo_list.addItem(QListWidgetItem(name))

    def _refresh_combo_region_choices(self) -> None:
        self._combo_regions_list.clear()
        for name in self.project.hud_regions:
            self._combo_regions_list.addItem(QListWidgetItem(name))
        self._sync_combo_region_selection()

    def _sync_combo_region_selection(self) -> None:
        """Ticks the multi-select region list to match self._selected_combo's
        current region_names -- called whenever the combo selection or the
        set of available HUD regions changes, so the two stay consistent."""
        self._loading_combo_fields = True
        try:
            selected_names = set(self._selected_combo.region_names) if self._selected_combo else set()
            for i in range(self._combo_regions_list.count()):
                item = self._combo_regions_list.item(i)
                item.setSelected(item.text() in selected_names)
        finally:
            self._loading_combo_fields = False

    def _on_combo_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._selected_combo = None
        else:
            self._selected_combo = self.project.hud_region_combos.get(current.text())
        self._loading_combo_fields = True
        try:
            self._combo_action_edit.setText(self._selected_combo.action_name if self._selected_combo else "")
        finally:
            self._loading_combo_fields = False
        self._sync_combo_region_selection()

    def _on_combo_regions_changed(self) -> None:
        if self._loading_combo_fields or self._selected_combo is None:
            return
        self._selected_combo.region_names = [
            self._combo_regions_list.item(i).text()
            for i in range(self._combo_regions_list.count())
            if self._combo_regions_list.item(i).isSelected()
        ]

    def _on_combo_action_edited(self) -> None:
        if self._loading_combo_fields or self._selected_combo is None:
            return
        self._selected_combo.action_name = self._combo_action_edit.text()

    def _add_hud_combo(self) -> None:
        name, ok = QInputDialog.getText(self, "Add HUD Combo", "Combo name:")
        if not ok or not name:
            return
        if name in self.project.hud_region_combos:
            QMessageBox.warning(self, "Add HUD Combo", f"Combo {name!r} already exists.")
            return
        self.project.add_hud_region_combo(HudRegionCombo(name=name))
        self._refresh_combo_list()
        self._log_line(f"Added HUD combo {name!r} -- select 2+ regions and set its Action name.")

    def _remove_hud_combo(self) -> None:
        item = self._combo_list.currentItem()
        if item is None:
            return
        self.project.remove_hud_region_combo(item.text())
        self._selected_combo = None
        self._refresh_combo_list()
        self._combo_action_edit.clear()
        self._sync_combo_region_selection()

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
        self._canvas.set_hud_regions(self._hud_region_markers(width, height))

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

    def _hud_region_markers(self, frame_w: int, frame_h: int):
        regions = []
        for region in self.project.hud_regions.values():
            x0, y0 = self._reference_to_frame(region.x, region.y, frame_w, frame_h)
            x1, y1 = self._reference_to_frame(region.x + region.width, region.y + region.height, frame_w, frame_h)
            label = f"{region.name} -> {region.action_name}" if region.action_name else region.name
            regions.append((x0, y0, x1, y1, label, region is self._selected_hud_region))
        return regions

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

    # -- record from device --------------------------------------------------------

    def _toggle_device_recording(self) -> None:
        if self._device_recorder is not None:
            self._finish_device_recording()
            return

        ref = self._require_reference_resolution()
        if ref is None:
            return  # already logged why

        self._sync_project_fields()
        recorder = DeviceEventRecorder(serial=self.project.serial or None)
        axis_ranges = recorder.probe_axis_ranges()
        if axis_ranges is None:
            self._log_line(
                "Record from Device BLOCKED: could not determine the touchscreen's raw coordinate "
                "range (`adb shell getevent -pl` found no device with \"touch\" in its name, or adb "
                "isn't reachable) -- without it, recorded raw coordinates can't be scaled into the "
                "project's reference resolution. Check the device is connected (`adb devices`) and "
                "the project's Device serial field is correct if more than one device is attached.")
            return
        rotation = recorder.probe_rotation()
        if rotation is None:
            self._log_line(
                "Record from Device BLOCKED: could not determine the display's current rotation "
                "(`adb shell dumpsys input` had no \"Viewport INTERNAL\" orientation line) -- without "
                "it, recorded coordinates can silently come out rotated/mirrored whenever the touch "
                "panel's native orientation doesn't match the display's current one (a real bug this "
                "was built to fix, not a hypothetical). Retry, or check the device is still connected.")
            return
        self._device_recording_axis_ranges = axis_ranges
        self._device_recording_rotation = rotation
        self._device_recorder = recorder
        recorder.start()
        self._record_device_btn.setText("Stop Recording")
        self._log_line(
            f"Recording real touches from the device directly (touch panel range "
            f"{axis_ranges[0]}x{axis_ranges[1]}, display rotation {rotation}) -- touch/drag on the "
            f"physical screen, then click 'Stop Recording'. This bypasses the mirror entirely, so "
            f"nothing needs to be visible in the canvas above while you do it.")

    def _finish_device_recording(self) -> None:
        recorder = self._device_recorder
        axis_ranges = self._device_recording_axis_ranges
        rotation = self._device_recording_rotation
        self._device_recorder = None
        self._record_device_btn.setText("Record from Device")

        touches = recorder.stop()
        self._log_line(f"Stopped recording: captured {len(touches)} raw touch transition(s).")
        gestures = segment_into_gestures(touches)
        if not gestures:
            self._log_line("No gestures captured -- nothing to import.")
            return

        ref = self._require_reference_resolution()
        if ref is None:
            self._log_line("Recording discarded: reference resolution became unset before it could be scaled.")
            return
        ref_w, ref_h = ref
        raw_x_max, raw_y_max = axis_ranges

        for i, gesture in enumerate(gestures):
            self._log_line(f"  touch {i + 1}: {self._describe_gesture(gesture)}")

        events = merge_gestures_into_events(gestures, raw_x_max, raw_y_max, ref_w, ref_h, rotation=rotation)
        if not events:
            self._log_line("Recording discarded: no usable events (all gestures were empty/positionless).")
            return

        plural = "es" if len(gestures) != 1 else ""
        name, ok = QInputDialog.getText(
            self, "Name Recorded Action",
            f"{len(gestures)} touch{plural} recorded (see log for each) -> {len(events)} events combined "
            f"into one action.\n\nName this action (Cancel to discard the whole recording):")
        if not ok or not name:
            self._log_line("Recording discarded (no name given).")
            return
        if name in self.project.actions:
            self._log_line(f"Recording discarded: action {name!r} already exists.")
            return

        self.project.add_action(Action(name=name, events=events,
                                        description=f"recorded from {len(gestures)} real device touch(es)"))
        self._refresh_action_list()
        self._warn_pointer_conflicts()
        self._log_line(f"Imported as action {name!r} ({len(events)} events from {len(gestures)} touch(es)).")

    @staticmethod
    def _describe_gesture(gesture: list) -> str:
        kinds = [t.kind for t in gesture]
        first = gesture[0]
        if len(gesture) <= 2 and "move" not in kinds:
            return f"Tap-like touch at raw ({first.x}, {first.y})"
        last = gesture[-1]
        duration_ms = round((last.t - first.t) * 1000)
        return (f"Drag from raw ({first.x}, {first.y}) to raw ({last.x}, {last.y}), "
                f"{len(gesture)} samples over {duration_ms}ms")

    # -- gameplay sessions --------------------------------------------------------

    def _refresh_session_list(self) -> None:
        self._session_list.clear()
        if self.project_path is None:
            return
        for path in project_io.list_sessions(self.project_path):
            item = QListWidgetItem(path.stem.removesuffix(".session"))
            item.setData(Qt.UserRole, str(path))
            self._session_list.addItem(item)

    def _toggle_session_recording(self) -> None:
        if self._session_recorder is not None:
            self._finish_session_recording()
            return
        if self.project_path is None:
            self._log_line("Record Gameplay Session BLOCKED: save the project first -- sessions are "
                            "saved next to project.yaml, in a recordings/ subfolder.")
            return

        ref = self._require_reference_resolution()
        if ref is None:
            return  # already logged why

        self._sync_project_fields()
        recorder = DeviceEventRecorder(serial=self.project.serial or None)
        axis_ranges = recorder.probe_axis_ranges()
        if axis_ranges is None:
            self._log_line(
                "Record Gameplay Session BLOCKED: could not determine the touchscreen's raw coordinate "
                "range (`adb shell getevent -pl` found no device with \"touch\" in its name, or adb "
                "isn't reachable). Check the device is connected (`adb devices`) and the project's "
                "Device serial field is correct if more than one device is attached.")
            return
        rotation = recorder.probe_rotation()
        if rotation is None:
            self._log_line(
                "Record Gameplay Session BLOCKED: could not determine the display's current rotation "
                "(`adb shell dumpsys input` had no \"Viewport INTERNAL\" orientation line). Retry, or "
                "check the device is still connected.")
            return
        self._session_recording_axis_ranges = axis_ranges
        self._session_recording_rotation = rotation
        self._session_recorder = recorder
        recorder.start()
        self._record_session_btn.setText("Stop Recording Session")
        self._log_line(
            f"Recording a gameplay session (touch panel range {axis_ranges[0]}x{axis_ranges[1]}, "
            f"display rotation {rotation}) -- play through the game on the physical screen, then "
            f"click 'Stop Recording Session'. Every touch is kept as its own raw event, not merged "
            f"into one action.")

    def _finish_session_recording(self) -> None:
        recorder = self._session_recorder
        axis_ranges = self._session_recording_axis_ranges
        rotation = self._session_recording_rotation
        self._session_recorder = None
        self._record_session_btn.setText("Record Gameplay Session")

        touches = recorder.stop()
        self._log_line(f"Stopped session recording: captured {len(touches)} raw touch transition(s).")
        gestures = segment_into_gestures(touches)
        if not gestures:
            self._log_line("No gestures captured -- nothing to save.")
            return

        ref = self._require_reference_resolution()
        if ref is None:
            self._log_line("Session discarded: reference resolution became unset before it could be scaled.")
            return
        ref_w, ref_h = ref
        raw_x_max, raw_y_max = axis_ranges

        events = merge_gestures_into_events(gestures, raw_x_max, raw_y_max, ref_w, ref_h, rotation=rotation)
        if not events:
            self._log_line("Session discarded: no usable events (all gestures were empty/positionless).")
            return

        name, ok = QInputDialog.getText(
            self, "Name Gameplay Session",
            f"{len(gestures)} touch(es) recorded -> {len(events)} raw events.\n\n"
            f"Name this session (Cancel to discard the whole recording):")
        if not ok or not name:
            self._log_line("Session discarded (no name given).")
            return

        session = GameplaySession(
            name=name, created_at=datetime.now(timezone.utc).isoformat(),
            source="device", reference_width=ref_w, reference_height=ref_h, events=events,
            notes=f"recorded from {len(gestures)} real device touch(es)")
        path = project_io.save_session(session, self.project_path)
        self._refresh_session_list()
        self._log_line(f"Saved gameplay session {name!r} to {path} ({len(events)} raw events, no "
                        f"classification yet -- see recordings/*.session.yaml's `segments` field).")

    def _selected_session_path(self) -> Path | None:
        item = self._session_list.currentItem()
        if item is None:
            self._log_line("No session selected.")
            return None
        return Path(item.data(Qt.UserRole))

    def _run_session_replay(self, mode: str) -> None:
        path = self._selected_session_path()
        if path is None:
            return
        if self.connection is None or not self.connection.connected:
            self._log_line("Replay ignored: not connected.")
            return
        ref = self._require_reference_resolution()
        if ref is None:
            return
        try:
            session = project_io.load_session(path)
        except Exception as e:  # noqa: BLE001 -- surfaced to the user, not swallowed
            self._log_line(f"Replay failed: could not load {path}: {e}")
            return
        ref_w, ref_h = ref
        self._session_player = SessionPlayer(self.connection, ref_w, ref_h, on_log=self._session_signals.logLine.emit)

        def worker() -> None:
            if mode == "raw":
                self._session_player.replay_raw(session)
            else:
                self._session_player.replay_classified(session, self.project.actions)

        threading.Thread(target=worker, daemon=True).start()

    def _replay_session_raw(self) -> None:
        self._run_session_replay("raw")

    def _replay_session_classified(self) -> None:
        self._run_session_replay("classified")

    def _stop_session_replay(self) -> None:
        if self._session_player is not None:
            self._session_player.stop()
            self._log_line("Replay stop requested.")

    def _classify_session(self) -> None:
        path = self._selected_session_path()
        if path is None:
            return
        if not self.project.hud_regions:
            self._log_line("Classify ignored: no HUD regions defined -- capture at least one first.")
            return
        try:
            session = project_io.load_session(path)
        except Exception as e:  # noqa: BLE001 -- surfaced to the user, not swallowed
            self._log_line(f"Classify failed: could not load {path}: {e}")
            return

        if session.segments:
            reply = QMessageBox.question(
                self, "Classify Session",
                f"{session.name!r} already has {len(session.segments)} segment(s). Overwrite them with a "
                f"fresh classification against the current HUD regions?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                self._log_line("Classify cancelled.")
                return

        session.segments = classify_session(
            session, self.project.hud_regions, self.project.hud_region_combos, on_log=self._log_line)
        for warning in session.validate(self.project.actions):
            self._log_line(f"  warning: {warning}")
        project_io.save_session(session, self.project_path)
        self._log_line(f"Saved classification to {path}.")

    def closeEvent(self, event) -> None:
        if self._device_recorder is not None:
            self._device_recorder.stop()
        if self._session_recorder is not None:
            self._session_recorder.stop()
        if self._session_player is not None:
            self._session_player.stop()
        if self._run_executor is not None:
            self._run_executor.stop()
        if self.connection is not None:
            self.connection.disconnect()
        super().closeEvent(event)
