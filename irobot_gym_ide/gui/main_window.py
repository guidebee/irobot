"""Main IDE window.

Layout: a left "Project" dock (connection settings, plus irobot's color
AgentStream thumbnail shown right after Connect/status); an always-visible
Live View (the interactive grayscale mirror) sitting above a "workflow"
QTabWidget (Define / Sessions / Game Run / Rewards / Observations /
Reset-Initial-State) in the central widget; tabified "Library" (every
defined Action/HUD Region/HUD Combo/Template, browsable from any tab) and
"Inspector" (detail editor for whatever's selected in Library) docks on the
right; and a collapsible "Log" dock at the bottom. See
docs/irobot_gym_ide_design.md for the broader rationale.

Click-to-test loop: select an action, click Connect, click on the live frame
to append events to it, click Test to send the whole action to the real
device and watch the canvas update with the result -- calibration happens
against the real device, not a guessed screenshot, and you find out
immediately whether a click landed on the right button.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidgetItem, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, QLabel, QScrollArea,
    QPlainTextEdit, QSplitter, QFileDialog, QMessageBox, QInputDialog, QTabWidget,
)
from PySide6.QtCore import Qt

from .. import io as project_io
from ..model import (
    Project, Action, EventKind, GameplaySession, GameRun, HudRegion, HudRegionCombo, ImageTemplate, PrimitiveEvent,
    classified_pointer_conflicts, conflicting_pointer_actions, orphan_releases,
)
from ..connection import LiveConnection
from ..device_recorder import DeviceEventRecorder, merge_gestures_into_events, segment_into_gestures
from ..dry_run import DryRunConnection
from ..gym_export import export_action_map
from ..hud_classifier import (
    build_game_run, classify_session, compare_replay_durations, diff_classifications, propose_actions,
    propose_combos,
)
from ..run_engine import GameRunExecutor, summarize_assertions
from ..session_replay import SessionPlayer
from .canvas import CanvasView
from .panels.define_panel import DefinePanel
from .panels.game_run_panel import GameRunPanel
from .panels.inspector_stack import InspectorStack
from .panels.library_panel import LibraryPanel
from .panels.observation_panel import ObservationPanel
from .panels.reset_panel import ResetPanel
from .panels.reward_panel import RewardPanel
from .panels.sessions_panel import SessionsPanel
from .thumbnail_view import ThumbnailView

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

        self._settings = QSettings("irobot", "GymIDE")

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
        self._selected_hud_region: HudRegion | None = None
        self._selected_combo: HudRegionCombo | None = None
        # per-field "loading" guards for Template/HudRegion/HudRegionCombo now
        # live inside InspectorStack's own detail-inspector widgets
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
        self._maybe_open_last_project()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_frame)
        self._poll_timer.start(POLL_MS)

        self._central_split_initialized = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._central_split_initialized:
            # QSplitter.setSizes() during/right after showEvent still gets
            # overridden by QMainWindow's own pending dock/central layout
            # pass -- deferring to the next event-loop iteration (after that
            # pass has finished) is what actually makes the 50/50 default
            # (video is the main working area) stick.
            self._central_split_initialized = True
            QTimer.singleShot(0, self._apply_default_central_split)

    def _apply_default_central_split(self) -> None:
        half = self._central_splitter.height() // 2
        self._central_splitter.setSizes([half, half])

    @staticmethod
    def _scrollable(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        return scroll

    # -- UI construction --------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()
        self._build_project_dock()
        self._build_library_and_inspector_docks()
        self._build_central_widget()
        self._build_log_dock()

    def _build_project_dock(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)

        form = QFormLayout()
        self._name_edit = QLineEdit(self.project.name)
        self._description_edit = QLineEdit(self.project.description)
        self._package_edit = QLineEdit(self.project.package)
        self._serial_edit = QLineEdit(self.project.serial)
        self._host_edit = QLineEdit(self.project.host)
        self._port_spin = QSpinBox(); self._port_spin.setRange(1, 65535); self._port_spin.setValue(self.project.port)
        self._ref_w_spin = QSpinBox(); self._ref_w_spin.setRange(0, 10000); self._ref_w_spin.setValue(self.project.reference_width)
        self._ref_h_spin = QSpinBox(); self._ref_h_spin.setRange(0, 10000); self._ref_h_spin.setValue(self.project.reference_height)
        self._time_scale_spin = QDoubleSpinBox()
        self._time_scale_spin.setRange(0.1, 10.0)
        self._time_scale_spin.setSingleStep(0.05)
        self._time_scale_spin.setDecimals(2)
        self._time_scale_spin.setValue(self.project.time_scale)
        self._time_scale_spin.setToolTip(
            "Multiplies every recorded/authored WAIT and Delay's real duration. Position already "
            "adapts automatically to a different device's detected resolution -- this is the one "
            "factor a recipient of a shared project tunes by hand for a device with a different "
            "game/animation speed. 1.00 reproduces the original author's pacing exactly.")
        form.addRow("Name", self._name_edit)
        form.addRow("Description", self._description_edit)
        form.addRow("Package", self._package_edit)
        form.addRow("Device serial", self._serial_edit)
        form.addRow("Host", self._host_edit)
        form.addRow("Port", self._port_spin)
        form.addRow("Reference width", self._ref_w_spin)
        form.addRow("Reference height", self._ref_h_spin)
        form.addRow("Time scale", self._time_scale_spin)
        for w in (self._name_edit, self._description_edit, self._package_edit, self._serial_edit, self._host_edit):
            w.editingFinished.connect(self._sync_project_fields)
        for w in (self._port_spin, self._ref_w_spin, self._ref_h_spin):
            w.valueChanged.connect(self._sync_project_fields)
        self._time_scale_spin.valueChanged.connect(self._sync_project_fields)
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

        self._thumbnail_view = ThumbnailView()
        left_layout.addWidget(self._thumbnail_view)
        left_layout.addStretch(1)

        left_dock = QDockWidget("Project", self)
        left_dock.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)

    def _build_library_and_inspector_docks(self) -> None:
        # "Library": every defined Action/HUD Region/HUD Combo/Image Template,
        # browsable regardless of which workflow tab is active (Game Run's
        # Compare/Find Template nodes and future Reward/Observation/Reset
        # stages all need to reference these).
        self._library = LibraryPanel()
        self._library.selectionChanged.connect(self._on_library_selection_changed)
        self._library.addRequested.connect(self._on_library_add)
        self._library.removeRequested.connect(self._on_library_remove)
        self._library.renameRequested.connect(self._on_library_rename)
        library_dock = QDockWidget("Library", self)
        library_dock.setWidget(self._library)
        self.addDockWidget(Qt.RightDockWidgetArea, library_dock)

        # "Inspector": a stacked widget showing whichever detail editor
        # matches the current Library selection.
        self._inspector_stack = InspectorStack()
        self._inspector = self._inspector_stack.action_inspector  # kept as a short alias; many call sites below
        self._inspector.actionChanged.connect(self._on_action_edited)
        self._inspector_stack.hud_region_inspector.regionEdited.connect(self._on_hud_region_rect_edited)
        inspector_dock = QDockWidget("Inspector", self)
        inspector_dock.setWidget(self._inspector_stack)
        self.addDockWidget(Qt.RightDockWidgetArea, inspector_dock)

        self.tabifyDockWidget(library_dock, inspector_dock)
        library_dock.raise_()

    def _build_central_widget(self) -> None:
        # Live View: the interactive grayscale mirror, always visible
        # regardless of the active workflow tab below it. (The color
        # AgentStream thumbnail lives in the Project dock, next to Connect.)
        self._canvas = CanvasView()
        self._canvas.pointClicked.connect(self._on_canvas_clicked)
        self._canvas.regionSelected.connect(self._on_region_selected)

        # Workflow tabs: today's Define/Sessions/Game Run stages, plus
        # placeholder tabs for the future Reward/Observation/Reset stages --
        # adding a stage later means adding a tab here, not restacking a dock.
        self._define_panel = DefinePanel()
        self._define_panel.test_action_btn.clicked.connect(self._test_action)
        self._define_panel.release_btn.clicked.connect(self._release_all)
        self._define_panel.record_device_btn.clicked.connect(self._toggle_device_recording)
        self._define_panel.capture_region_btn.toggled.connect(self._toggle_capture_mode)
        self._define_panel.capture_hud_region_btn.toggled.connect(self._toggle_hud_capture_mode)
        self._define_panel.add_combo_btn.clicked.connect(self._add_hud_combo)
        self._define_panel.remove_combo_btn.clicked.connect(self._remove_hud_combo)
        self._define_panel.export_action_map_btn.clicked.connect(self._export_action_map)
        # short aliases -- kept so the rest of this class's methods (_on_canvas_clicked,
        # _toggle_capture_mode, _toggle_device_recording, etc.) don't need renaming
        self._new_kind_combo = self._define_panel.new_kind_combo
        self._new_pointer_spin = self._define_panel.new_pointer_spin
        self._live_send_checkbox = self._define_panel.live_send_checkbox
        self._record_device_btn = self._define_panel.record_device_btn
        self._capture_region_btn = self._define_panel.capture_region_btn
        self._capture_hud_region_btn = self._define_panel.capture_hud_region_btn

        self._sessions_panel = SessionsPanel()
        self._sessions_panel.record_session_btn.clicked.connect(self._toggle_session_recording)
        self._sessions_panel.classify_session_btn.clicked.connect(self._classify_session)
        self._sessions_panel.replay_raw_btn.clicked.connect(self._replay_session_raw)
        self._sessions_panel.replay_classified_btn.clicked.connect(self._replay_session_classified)
        self._sessions_panel.stop_replay_btn.clicked.connect(self._stop_session_replay)
        self._sessions_panel.match_tolerance_spin.valueChanged.connect(self._on_match_tolerance_changed)
        self._record_session_btn = self._sessions_panel.record_session_btn
        self._session_list = self._sessions_panel.session_list

        self._game_run_panel = GameRunPanel(
            get_action_names=lambda: list(self.project.actions.keys()),
            get_template_names=lambda: list(self.project.templates.keys()))
        self._game_run_panel.add_run_btn.clicked.connect(self._add_run)
        self._game_run_panel.remove_run_btn.clicked.connect(self._remove_run)
        self._game_run_panel.run_all_btn.clicked.connect(self._run_all_game_runs)
        self._game_run_panel.run_list.currentItemChanged.connect(self._on_run_selected)
        self._run_list = self._game_run_panel.run_list
        self._run_editor = self._game_run_panel.run_editor
        self._run_editor.graphChanged.connect(self._on_run_graph_changed)
        self._run_editor.runRequested.connect(self._run_game_run)
        self._run_editor.previewRequested.connect(self._preview_game_run)
        self._run_editor.stopRequested.connect(self._stop_game_run)

        # Each page is wrapped in a scroll area so a tall page's stacked
        # controls (e.g. Define's) can't force the whole QTabWidget's
        # minimum height above what the splitter needs to give the video
        # canvas its default half of the window -- content that doesn't fit
        # simply scrolls instead of pushing the video pane down.
        tabs = QTabWidget()
        tabs.addTab(self._scrollable(self._define_panel), "Define")
        tabs.addTab(self._scrollable(self._sessions_panel), "Sessions")
        tabs.addTab(self._game_run_panel, "Game Run")   # its own node canvas already scrolls/pans
        tabs.addTab(self._scrollable(RewardPanel()), "Rewards")
        tabs.addTab(self._scrollable(ObservationPanel()), "Observations")
        tabs.addTab(self._scrollable(ResetPanel()), "Reset / Initial State")

        self._central_splitter = QSplitter(Qt.Vertical)
        self._central_splitter.addWidget(self._canvas)
        self._central_splitter.addWidget(tabs)
        self._central_splitter.setStretchFactor(0, 1)   # video is the main working area -- default to half the window
        self._central_splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self._central_splitter)

    def _build_log_dock(self) -> None:
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        log_dock = QDockWidget("Log", self)
        log_dock.setWidget(self._log)
        self.addDockWidget(Qt.BottomDockWidgetArea, log_dock)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        menu.addAction("New Project", self._new_project)
        menu.addAction("Open Project...", self._open_project)
        self._recent_menu = menu.addMenu("Recent Projects")
        self._update_recent_menu()
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
        self.project.description = self._description_edit.text()
        self.project.package = self._package_edit.text()
        self.project.serial = self._serial_edit.text()
        self.project.host = self._host_edit.text()
        self.project.port = self._port_spin.value()
        self.project.reference_width = self._ref_w_spin.value()
        self.project.reference_height = self._ref_h_spin.value()
        self.project.time_scale = self._time_scale_spin.value()
        if self.connection is not None:
            self.connection.time_scale = self.project.time_scale
        self.setWindowTitle(f"irobot Gym IDE - {self.project.name}")

    def _load_project_into_fields(self) -> None:
        self._loading_fields = True
        try:
            self._name_edit.setText(self.project.name)
            self._description_edit.setText(self.project.description)
            self._package_edit.setText(self.project.package)
            self._serial_edit.setText(self.project.serial)
            self._host_edit.setText(self.project.host)
            self._port_spin.setValue(self.project.port)
            self._ref_w_spin.setValue(self.project.reference_width)
            self._ref_h_spin.setValue(self.project.reference_height)
            self._time_scale_spin.setValue(self.project.time_scale)
            self._sessions_panel.match_tolerance_spin.setValue(self.project.action_match_tolerance_px)
        finally:
            self._loading_fields = False
        if self.connection is not None:
            self.connection.time_scale = self.project.time_scale
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
        project_dir = QFileDialog.getExistingDirectory(self, "Open Project (select its folder)")
        if not project_dir:
            return
        path = str(Path(project_dir) / project_io.PROJECT_FILENAME)
        self._load_project_from_path(path)

    def _load_project_from_path(self, path: str) -> bool:
        try:
            self.project = project_io.load_project(path)
        except Exception as e:  # noqa: BLE001 -- surfaced to the user, not swallowed
            QMessageBox.critical(self, "Open failed", str(e))
            return False
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
        self._add_recent_project(path)
        return True

    def _save_project(self) -> None:
        if self.project_path is None:
            self._save_project_as()
            return
        self.project.updated_at = datetime.now(timezone.utc).isoformat()
        project_io.save_project(self.project, self.project_path)
        self._log_line(f"Saved {self.project_path}")

    def _save_project_as(self) -> None:
        project_dir = QFileDialog.getExistingDirectory(self, "Save Project As (select or create a folder)")
        if not project_dir:
            return
        self.project_path = Path(project_dir) / project_io.PROJECT_FILENAME
        self.project.updated_at = datetime.now(timezone.utc).isoformat()
        project_io.save_project(self.project, self.project_path)
        self._refresh_session_list()
        self._log_line(f"Saved {self.project_path}")
        self._add_recent_project(str(self.project_path))

    # -- recent projects --------------------------------------------------------

    _MAX_RECENT_PROJECTS = 10

    def _recent_projects(self) -> list[str]:
        value = self._settings.value("recent_projects", [])
        if not value:
            return []
        # QSettings collapses a single-element string list back to a bare str
        # on some platforms/backends -- normalize so callers always get a list.
        if isinstance(value, str):
            return [value]
        return list(value)

    def _add_recent_project(self, path: str) -> None:
        paths = [p for p in self._recent_projects() if p != path]
        paths.insert(0, path)
        paths = paths[: self._MAX_RECENT_PROJECTS]
        self._settings.setValue("recent_projects", paths)
        self._settings.setValue("last_project", path)
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        paths = self._recent_projects()
        if not paths:
            action = self._recent_menu.addAction("(none)")
            action.setEnabled(False)
            return
        for path in paths:
            self._recent_menu.addAction(path, lambda checked=False, p=path: self._open_recent_project(p))
        self._recent_menu.addSeparator()
        self._recent_menu.addAction("Clear Recent Projects", self._clear_recent_projects)

    def _open_recent_project(self, path: str) -> None:
        if not Path(path).exists():
            QMessageBox.warning(self, "Open failed", f"{path} no longer exists.")
            self._settings.setValue("recent_projects", [p for p in self._recent_projects() if p != path])
            self._update_recent_menu()
            return
        self._load_project_from_path(path)

    def _clear_recent_projects(self) -> None:
        self._settings.setValue("recent_projects", [])
        self._update_recent_menu()

    def _maybe_open_last_project(self) -> None:
        last = self._settings.value("last_project", "")
        if not last or not Path(last).exists():
            return
        self._load_project_from_path(last)

    # -- actions --------------------------------------------------------

    def _refresh_action_list(self) -> None:
        self._library.refresh_actions(list(self.project.actions.keys()))

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
        if self._selected_action is None:
            return
        self.project.remove_action(self._selected_action.name)
        self._refresh_action_list()
        self._inspector_stack.show_action(None)
        self._selected_action = None
        self._on_run_graph_changed()

    # -- Library dock: one selection/add/remove handler for every category --

    def _on_library_selection_changed(self, category: str, name: str) -> None:
        self._selected_action = None
        self._selected_template = None
        self._selected_hud_region = None
        self._selected_combo = None
        if category == "action":
            self._selected_action = self.project.actions.get(name)
            self._inspector_stack.show_action(self._selected_action)
        elif category == "template":
            self._selected_template = self.project.templates.get(name)
            self._inspector_stack.show_template(self._selected_template)
        elif category == "hud_region":
            self._selected_hud_region = self.project.hud_regions.get(name)
            self._inspector_stack.show_hud_region(self._selected_hud_region)
        elif category == "hud_combo":
            self._selected_combo = self.project.hud_region_combos.get(name)
            self._inspector_stack.show_hud_combo(self._selected_combo)
        else:
            self._inspector_stack.show_nothing()

    def _on_library_add(self, category: str) -> None:
        if category == "action":
            self._add_action()

    def _on_library_remove(self, category: str, _name: str) -> None:
        if category == "action":
            self._remove_action()
        elif category == "template":
            self._remove_template()
        elif category == "hud_region":
            self._remove_hud_region()

    def _on_library_rename(self, category: str, name: str) -> None:
        if category == "action":
            self._rename_action(name)
        elif category == "hud_region":
            self._rename_hud_region(name)

    def _rename_action(self, old_name: str) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename Action", "New name:", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return
        try:
            updated = self.project.rename_action(old_name, new_name)
        except ValueError as e:
            QMessageBox.warning(self, "Rename Action", str(e))
            return
        self._refresh_action_list()
        self._refresh_hud_region_list()
        self._refresh_combo_list()
        self._on_run_graph_changed()
        self._library.selectionChanged.emit("action", new_name)
        self._log_line(
            f"Renamed action {old_name!r} to {new_name!r} ({updated} reference(s) updated across "
            f"HUD regions/combos/runs).")

    def _rename_hud_region(self, old_name: str) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename HUD Region", "New name:", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return
        try:
            updated = self.project.rename_hud_region(old_name, new_name)
        except ValueError as e:
            QMessageBox.warning(self, "Rename HUD Region", str(e))
            return
        self._refresh_hud_region_list()
        self._refresh_combo_list()
        self._library.selectionChanged.emit("hud_region", new_name)
        self._log_line(f"Renamed HUD region {old_name!r} to {new_name!r} ({updated} combo reference(s) updated).")

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

    def _run_all_game_runs(self) -> None:
        """Runs every Game Run in the project, in turn, against the live device -- a
        regression suite over whatever Assert nodes each one has (see
        ACTION_CLASSIFICATION_DESIGN.md G16). Each run's own assertion labels get prefixed
        with that run's name (e.g. "level1_run:cleared_gap") directly on the shared executor's
        `assertions` list, so `_on_run_finished`'s existing summarize_assertions() call -- no
        changes needed there -- reports one aggregate PASS/FAIL summary traceable back to
        which run each failure came from, instead of needing separate per-run reporting
        machinery."""
        if self.connection is None or not self.connection.connected:
            self._run_editor.log_line("Run All ignored: not connected.")
            return
        ref = self._require_reference_resolution()
        if ref is None:
            return
        ref_w, ref_h = ref
        runs = list(self.project.runs.values())
        if not runs:
            self._run_editor.log_line("Run All: project has no Game Runs.")
            return
        executor = GameRunExecutor(
            self.connection, self.project.actions, ref_w, ref_h,
            on_log=self._run_signals.logLine.emit, templates=self.project.templates)
        self._run_executor = executor
        self._run_editor.set_running(True)
        self._run_editor.log_line(f"Running all {len(runs)} Game Run(s) as a regression suite...")

        def worker() -> None:
            try:
                for run in runs:
                    if executor.stopped:
                        break
                    start = len(executor.assertions)
                    self._run_signals.logLine.emit(f"--- {run.name} ---")
                    executor.run(run)
                    executor.assertions[start:] = [
                        (f"{run.name}:{label}", ok, similarity)
                        for label, ok, similarity in executor.assertions[start:]
                    ]
            finally:
                self._run_signals.finished.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _preview_game_run(self, game_run: GameRun | None) -> None:
        """Runs `game_run` against a DryRunConnection instead of the live device -- see
        dry_run.py's module docstring: GameRunExecutor needed no changes to support this,
        just a different `connection`. Works with no device connected at all; still needs a
        reference resolution (the Actions themselves are defined in that space, dry run or
        not)."""
        if game_run is None:
            return
        ref_w, ref_h = self.project.reference_width or 1, self.project.reference_height or 1
        dry_connection = DryRunConnection(time_scale=self.project.time_scale, on_log=self._run_signals.logLine.emit)
        executor = GameRunExecutor(
            dry_connection, self.project.actions, ref_w, ref_h,
            on_log=self._run_signals.logLine.emit, templates=self.project.templates)
        self._run_executor = executor
        self._run_editor.set_running(True)
        self._run_editor.log_line(f"Previewing {game_run.name!r} (dry run, no device)...")

        def worker() -> None:
            try:
                executor.run(game_run)
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
        if self._run_executor is not None and self._run_executor.assertions:
            self._run_editor.log_line(summarize_assertions(self._run_executor.assertions))

    # -- compare templates --------------------------------------------------------

    def _refresh_template_list(self) -> None:
        self._library.refresh_templates(self.project.templates)

    def _remove_template(self) -> None:
        if self._selected_template is None:
            return
        self.project.remove_template(self._selected_template.name)
        self._selected_template = None
        self._refresh_template_list()
        self._inspector_stack.show_template(None)
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
        self._library.refresh_hud_regions(list(self.project.hud_regions.keys()))
        self._refresh_combo_region_choices()

    def _on_hud_region_rect_edited(self) -> None:
        """HudRegionInspector.regionEdited -- refreshes the canvas overlay
        immediately when connected, rather than waiting for the next poll tick."""
        if self.connection is None:
            return
        frame = self.connection.latest_frame()
        if frame is None:
            return
        width, height, _ndarray = frame
        self._canvas.set_hud_regions(self._hud_region_markers(width, height))

    def _remove_hud_region(self) -> None:
        if self._selected_hud_region is None:
            return
        self.project.remove_hud_region(self._selected_hud_region.name)
        self._selected_hud_region = None
        self._refresh_hud_region_list()
        self._inspector_stack.show_hud_region(None)

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
        self._library.refresh_hud_combos(list(self.project.hud_region_combos.keys()))

    def _refresh_combo_region_choices(self) -> None:
        self._inspector_stack.set_region_choices(list(self.project.hud_regions.keys()))

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
        if self._selected_combo is None:
            return
        self.project.remove_hud_region_combo(self._selected_combo.name)
        self._selected_combo = None
        self._refresh_combo_list()
        self._inspector_stack.show_hud_combo(None)

    def _export_action_map(self) -> None:
        default_dir = str(self.project_path.parent) if self.project_path is not None else ""
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export Action Map", f"{default_dir}/action_map.yaml", "YAML files (*.yaml)")
        if not path:
            return
        action_map = export_action_map(self.project, on_log=self._log_line)
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(action_map, f, sort_keys=False, allow_unicode=True)
        except OSError as e:
            QMessageBox.critical(self, "Export Action Map", str(e))
            return
        self._log_line(
            f"Exported Action Map to {path} ({len(action_map['buttons'])} button(s), "
            f"{len(action_map['macros'])} macro(s){', ' + str(len(action_map['compound_macros'])) + ' compound macro(s)' if 'compound_macros' in action_map else ''}).")

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
        self.connection.time_scale = self.project.time_scale
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
        thumbnail = self.connection.latest_thumbnail()
        if thumbnail is not None:
            self._thumbnail_view.update_thumbnail(*thumbnail)

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
                    f"Note: project Reference width/height is {ref_w}x{ref_h}, but this device reports "
                    f"{dw}x{dh} -- e.g. a project shared from a different device. LiveConnection now "
                    f"rescales every touch event's position automatically to match (see "
                    f"ACTION_CLASSIFICATION_DESIGN.md G11), so this is informational, not an error; only "
                    f"click 'Apply Detected Resolution' if you actually want to re-calibrate this "
                    f"project's own Reference width/height to this device permanently (that rewrites the "
                    f"stored value, not the coordinates -- re-check placements against the canvas after).")
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

    def _on_match_tolerance_changed(self, value: int) -> None:
        if self._loading_fields:
            return
        self.project.action_match_tolerance_px = value

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

        tolerance = self.project.action_match_tolerance_px
        new_segments = classify_session(
            session, self.project.hud_regions, self.project.hud_region_combos,
            project_actions=self.project.actions, position_tolerance_px=tolerance, on_log=self._log_line)

        if session.segments:
            diff = diff_classifications(session.segments, new_segments)
            reply = QMessageBox.question(
                self, "Classify Session",
                f"{session.name!r} already has {len(session.segments)} segment(s). A fresh classification "
                f"against the current HUD regions/actions would give:\n\n"
                f"  {diff['unchanged']} unchanged\n"
                f"  {diff['changed']} changed to a different action\n"
                f"  {diff['added']} newly classified (previously unknown/uncovered)\n"
                f"  {diff['removed']} no longer classified\n\n"
                f"Overwrite the existing segments with this?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                self._log_line("Classify cancelled.")
                return

        session.segments = new_segments
        for warning in session.validate(self.project.actions):
            self._log_line(f"  warning: {warning}")
        for warning in classified_pointer_conflicts(session.segments, self.project.actions):
            self._log_line(f"  warning: {warning}")
        project_io.save_session(session, self.project_path)
        self._log_line(f"Saved classification to {path}.")

        duration = compare_replay_durations(session, self.project.actions)
        if duration["mismatches"]:
            self._log_line(
                f"Timing check: Replay Raw would take ~{duration['raw_frames']} scripted frame(s); "
                f"Replay Classified would take ~{duration['classified_frames']} (using each segment's "
                f"named action's own timing, not the raw recording). {len(duration['mismatches'])} "
                f"segment(s) diverge from what was actually recorded:")
            for label, action_name, recorded, action_frames in duration["mismatches"]:
                self._log_line(
                    f"  {label!r} ({action_name!r}): recorded {recorded} frame(s), the action itself "
                    f"only waits {action_frames} frame(s) -- if this action is meant to reproduce a "
                    f"sustained hold/mash rather than a quick move, consider not folding it into a "
                    f"HUD Combo (see ACTION_CLASSIFICATION_DESIGN.md G10).")

        proposals = propose_actions(session, self.project.actions, position_tolerance_px=tolerance,
                                     on_log=self._log_line)
        if proposals:
            names = sorted(proposals)
            dup_names = sorted(n for n, a in proposals.items() if "possible duplicate" in a.description)
            dup_note = f"\n\n({len(dup_names)} flagged as a possible duplicate of an existing action: " \
                       f"{', '.join(dup_names)})" if dup_names else ""
            reply = QMessageBox.question(
                self, "Add Proposed Actions",
                f"Classification proposes {len(proposals)} new action definition(s):\n\n{', '.join(names)}"
                f"{dup_note}\n\nAdd them to the project? You can rename, edit, or delete any of them afterward "
                f"in the Inspector.",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                self._log_line("Proposed actions discarded (not added to the project).")
            else:
                for action in proposals.values():
                    self.project.add_action(action)
                self._refresh_action_list()
                self._warn_pointer_conflicts()
                self._log_line(
                    f"Added {len(proposals)} proposed action(s) to the project ({', '.join(names)}) -- "
                    f"review/rename/edit them in the Inspector, then Save Project to keep them.")

        combo_proposals = propose_combos(session, self.project.hud_regions, self.project.hud_region_combos,
                                          on_log=self._log_line)
        if combo_proposals:
            combo_names = sorted(combo_proposals)
            reply = QMessageBox.question(
                self, "Add Proposed HUD Combos",
                f"This session also has {len(combo_proposals)} recurring concurrent-region combination(s) "
                f"with no matching HUD Combo defined:\n\n{', '.join(combo_names)}\n\n"
                f"Add them as new HUD Combos? A future classification pass will then propose the backing "
                f"action(s) for each, same as any other not-yet-real action name.",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                for combo in combo_proposals.values():
                    self.project.add_hud_region_combo(combo)
                self._refresh_combo_list()
                self._log_line(
                    f"Added {len(combo_proposals)} proposed HUD combo(s) to the project ({', '.join(combo_names)}) "
                    f"-- re-classify to fold their gestures in, then Save Project to keep them.")
            else:
                self._log_line("Proposed HUD combos discarded (not added to the project).")

        if session.segments:
            self._offer_build_game_run(session)

    def _offer_build_game_run(self, session: GameplaySession) -> None:
        """Offers to turn `session`'s just-computed classification into a real, editable
        GameRun graph -- the durable counterpart to "Replay Classified" (see
        hud_classifier.build_game_run's docstring). Overwrites a same-named existing run only
        on confirmation, same "ask before clobbering" convention _classify_session's own
        segment-overwrite prompt already uses."""
        run_name = f"{session.name}_run"
        existing = run_name in self.project.runs
        prompt = (
            f"A Game Run named {run_name!r} already exists. Replace it with a fresh graph built from "
            f"this session's current classification?"
            if existing else
            f"Build a Game Run graph {run_name!r} from this session's {len(session.segments)} classified "
            f"segment(s) -- one Action node per segment, chained with Delay nodes reproducing the real "
            f"recorded gaps -- so it's reusable/editable from the Game Run tab like any hand-authored run?"
        )
        reply = QMessageBox.question(self, "Create Game Run", prompt, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            self._log_line("Game Run not created/updated from this classification.")
            return
        run = build_game_run(session, run_name, self.project.actions)
        self.project.add_run(run)
        self._refresh_run_list()
        self._log_line(
            f"{'Replaced' if existing else 'Created'} Game Run {run_name!r} from session {session.name!r}'s "
            f"classification ({len(run.nodes)} node(s)) -- Save Project to keep it.")

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
