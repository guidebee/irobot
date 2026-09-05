"""Node-graph editor for a GameRun: drag nodes around a canvas, drag from a
node's output port to another node's input port to connect them (a plain
node fires all its outgoing connections concurrently -- that's how parallel
branches are authored; a node with more than one incoming connection waits
for all of them, i.e. a join), plus a toolbar to add ACTION/DELAY/REPEAT
nodes and to Run/Stop the graph against the live connection. See
model.py's GameRun docstring for the exact fork/join/repeat semantics this
is a front-end for, and run_engine.py for the executor this drives.

Kept deliberately plain next to a "real" node-editor library: rectangles,
circles, and QGraphicsPathItem lines, no auto-layout, no minimap -- matches
this package's stated "start simple" scope (see model.py's module
docstring) applied to the run graph instead of the event list.
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..model import GameRun, RunEdge, RunNode, RunNodeKind, run_pointer_conflicts

_NODE_W, _NODE_H = 140, 56
_PORT_R = 6

_KIND_COLORS = {
    RunNodeKind.ACTION: QColor("#3498db"),
    RunNodeKind.DELAY: QColor("#95a5a6"),
    RunNodeKind.REPEAT: QColor("#e67e22"),
    RunNodeKind.COMPARE: QColor("#8e44ad"),
    RunNodeKind.FIND_TEMPLATE: QColor("#16a085"),
    RunNodeKind.ASSERT: QColor("#27ae60"),
}

# Node kinds with more than one named output port, each capped at one connection via
# the GUI (see RunGraphScene.try_add_edge) -- every other kind has a single "out" port.
_MULTI_PORT_KINDS = {
    RunNodeKind.REPEAT: ("body", "after"),
    RunNodeKind.COMPARE: ("match", "no_match"),
    RunNodeKind.FIND_TEMPLATE: ("found", "not_found"),
}

# Node kinds whose properties panel shows the template combo (see RunEditorWidget). ASSERT
# reuses COMPARE's template check but reports PASS/FAIL instead of branching -- see
# model.RunNodeKind.ASSERT.
_TEMPLATE_KINDS = (RunNodeKind.COMPARE, RunNodeKind.FIND_TEMPLATE, RunNodeKind.ASSERT)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class PortItem(QGraphicsEllipseItem):
    """A small circle anchored to a NodeItem's edge. `role` is "in" for the
    single input port every node has, or "out"/"body"/"after"/"match"/
    "no_match"/"found"/"not_found" for an output port -- see RunEdge.via for
    what the named roles mean (REPEAT's "body"/"after", COMPARE's "match"/
    "no_match", FIND_TEMPLATE's "found"/"not_found"; every other node kind
    has a single "out" output port)."""

    def __init__(self, node_item: "NodeItem", role: str):
        super().__init__(-_PORT_R, -_PORT_R, _PORT_R * 2, _PORT_R * 2, parent=node_item)
        self.node_item = node_item
        self.role = role
        self.setBrush(QBrush(QColor("#2c3e50")))
        self.setPen(QPen(QColor("#ecf0f1"), 1))
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setZValue(2)


class NodeItem(QGraphicsRectItem):
    def __init__(self, node: RunNode, scene: "RunGraphScene"):
        super().__init__(0, 0, _NODE_W, _NODE_H)
        self.node = node
        self._gscene = scene
        self.setPos(node.x, node.y)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                       | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QBrush(_KIND_COLORS.get(node.kind, QColor("#7f8c8d"))))
        self.setPen(QPen(QColor("#2c3e50"), 2))
        self.setZValue(1)

        self._label = QGraphicsSimpleTextItem(self)
        self._label.setBrush(QBrush(QColor("white")))
        self._label.setPos(6, 4)
        self.refresh_label()

        self.in_port = PortItem(self, "in")
        self.in_port.setPos(0, _NODE_H / 2)
        self.out_ports: dict = {}
        if node.kind in _MULTI_PORT_KINDS:
            first_role, second_role = _MULTI_PORT_KINDS[node.kind]
            self._add_out_port(first_role, QPointF(_NODE_W, _NODE_H * 0.3))
            self._add_out_port(second_role, QPointF(_NODE_W, _NODE_H * 0.7))
        else:
            self._add_out_port("out", QPointF(_NODE_W, _NODE_H / 2))

    def _add_out_port(self, role: str, pos: QPointF) -> None:
        port = PortItem(self, role)
        port.setPos(pos)
        self.out_ports[role] = port

    def refresh_label(self) -> None:
        node = self.node
        if node.kind == RunNodeKind.ACTION:
            text = f"[{node.action_name or '(pick action)'}]"
        elif node.kind == RunNodeKind.DELAY:
            text = f"delay {node.frames}f"
        elif node.kind == RunNodeKind.ASSERT:
            text = f"{node.label or '(no label)'} [{node.template_name or '(pick template)'}]"
        elif node.kind in (RunNodeKind.COMPARE, RunNodeKind.FIND_TEMPLATE):
            text = f"[{node.template_name or '(pick template)'}]"
        else:
            text = f"repeat x{node.times}"
        self._label.setText(f"{node.kind.value}\n{text}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.node.x, self.node.y = self.pos().x(), self.pos().y()
            self._gscene.update_edges_for_node(self.node.id)
        return super().itemChange(change, value)

    def port_scene_pos(self, role: str) -> QPointF:
        port = self.in_port if role == "in" else self.out_ports[role]
        return port.scenePos()


class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge: RunEdge, source_item: NodeItem, target_item: NodeItem):
        super().__init__()
        self.edge = edge
        self.source_item = source_item
        self.target_item = target_item
        self.setPen(QPen(QColor("#34495e"), 2))
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(0)
        self.update_path()

    def update_path(self) -> None:
        start = self.source_item.port_scene_pos(self.edge.via)
        end = self.target_item.port_scene_pos("in")
        dx = max(abs(end.x() - start.x()) * 0.5, 40)
        path = QPainterPath(start)
        path.cubicTo(start + QPointF(dx, 0), end - QPointF(dx, 0), end)
        self.setPath(path)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen = QPen(QColor("#e74c3c") if self.isSelected() else QColor("#34495e"), 2)
        painter.setPen(pen)
        painter.drawPath(self.path())


class RunGraphScene(QGraphicsScene):
    graphChanged = Signal()
    nodeSelected = Signal(object)   # RunNode or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game_run: GameRun | None = None
        self._node_items: dict = {}
        self._edge_items: dict = {}
        self._drag_source: tuple | None = None   # (NodeItem, role) while dragging a new connection
        self._drag_line: QGraphicsPathItem | None = None
        self.selectionChanged.connect(self._on_selection_changed)

    # -- (re)building the scene from a GameRun --------------------------------------------------------

    def load(self, game_run: GameRun) -> None:
        self.clear()
        self._node_items = {}
        self._edge_items = {}
        self._drag_source = None
        self._drag_line = None
        self.game_run = game_run
        if game_run is None:
            return
        for node in game_run.nodes.values():
            self._add_node_item(node)
        for edge in game_run.edges:
            self._add_edge_item(edge)

    def _add_node_item(self, node: RunNode) -> NodeItem:
        item = NodeItem(node, self)
        self.addItem(item)
        self._node_items[node.id] = item
        return item

    def _add_edge_item(self, edge: RunEdge) -> None:
        source_item = self._node_items.get(edge.source)
        target_item = self._node_items.get(edge.target)
        if source_item is None or target_item is None:
            return   # dangling reference -- validate() will flag it; nothing to draw
        item = EdgeItem(edge, source_item, target_item)
        self.addItem(item)
        self._edge_items[edge.id] = item

    def update_edges_for_node(self, node_id: str) -> None:
        for edge_id, item in self._edge_items.items():
            if item.edge.source == node_id or item.edge.target == node_id:
                item.update_path()

    # -- mutating the model from the GUI --------------------------------------------------------

    def add_node(self, kind: RunNodeKind, x: float = 20, y: float = 20) -> RunNode:
        node = RunNode(id=_new_id(), kind=kind, x=x, y=y)
        self.game_run.add_node(node)
        self._add_node_item(node)
        self.graphChanged.emit()
        return node

    def remove_selected(self) -> None:
        for gitem in list(self.selectedItems()):
            if isinstance(gitem, NodeItem):
                self._remove_node(gitem.node.id)
            elif isinstance(gitem, EdgeItem):
                self._remove_edge(gitem.edge.id)
        self.graphChanged.emit()
        self.nodeSelected.emit(None)

    def _remove_node(self, node_id: str) -> None:
        for edge_id in [eid for eid, item in self._edge_items.items()
                        if item.edge.source == node_id or item.edge.target == node_id]:
            self._remove_edge(edge_id)
        item = self._node_items.pop(node_id, None)
        if item is not None:
            self.removeItem(item)
        self.game_run.remove_node(node_id)

    def _remove_edge(self, edge_id: str) -> None:
        item = self._edge_items.pop(edge_id, None)
        if item is not None:
            self.removeItem(item)
        self.game_run.remove_edge(edge_id)

    def try_add_edge(self, source_item: NodeItem, role: str, target_item: NodeItem) -> None:
        if source_item is target_item:
            return
        if source_item.node.kind not in _MULTI_PORT_KINDS and self.game_run.outgoing(source_item.node.id, via=role):
            return   # a plain node's single "out" port -- one connection is enough to fork from
        if role in ("body", "after", "match", "no_match", "found", "not_found") \
                and self.game_run.outgoing(source_item.node.id, via=role):
            return   # a repeat/compare/find_template node's named port already has its one connection
        edge = RunEdge(id=_new_id(), source=source_item.node.id, target=target_item.node.id, via=role)
        self.game_run.add_edge(edge)
        self._add_edge_item(edge)
        self.graphChanged.emit()

    def _on_selection_changed(self) -> None:
        selected = [g for g in self.selectedItems() if isinstance(g, NodeItem)]
        self.nodeSelected.emit(selected[0].node if len(selected) == 1 else None)

    # -- interactive connection dragging --------------------------------------------------------

    def _port_at(self, pos: QPointF):
        for gitem in self.items(pos):
            if isinstance(gitem, PortItem):
                return gitem
        return None

    def mousePressEvent(self, event) -> None:
        port = self._port_at(event.scenePos())
        if port is not None and port.role != "in":
            self._drag_source = (port.node_item, port.role)
            self._drag_line = QGraphicsPathItem()
            self._drag_line.setPen(QPen(QColor("#e74c3c"), 2, Qt.DashLine))
            self.addItem(self._drag_line)
            self._update_drag_line(event.scenePos())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_source is not None:
            self._update_drag_line(event.scenePos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_source is not None:
            source_item, role = self._drag_source
            target_port = self._port_at(event.scenePos())
            if target_port is not None and target_port.role == "in" and target_port.node_item is not source_item:
                self.try_add_edge(source_item, role, target_port.node_item)
            self.removeItem(self._drag_line)
            self._drag_line = None
            self._drag_source = None
            return
        super().mouseReleaseEvent(event)

    def _update_drag_line(self, end: QPointF) -> None:
        source_item, role = self._drag_source
        start = source_item.port_scene_pos(role)
        path = QPainterPath(start)
        path.lineTo(end)
        self._drag_line.setPath(path)


class RunGraphView(QGraphicsView):
    def __init__(self, scene: RunGraphScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setSceneRect(QRectF(0, 0, 4000, 4000))
        self.setDragMode(QGraphicsView.RubberBandDrag)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.scene().remove_selected()
            return
        super().keyPressEvent(event)


class RunEditorWidget(QWidget):
    """One GameRun's editor: toolbar + graph canvas + node properties + run
    log. `get_action_names`/`get_action` let this stay decoupled from
    Project -- MainWindow supplies live lookups instead of a stale copy."""

    graphChanged = Signal()
    runRequested = Signal(object)   # GameRun
    previewRequested = Signal(object)   # GameRun -- run against a DryRunConnection, no device
    stopRequested = Signal()

    def __init__(self, get_action_names, get_template_names=lambda: [], parent=None):
        super().__init__(parent)
        self._get_action_names = get_action_names
        self._get_template_names = get_template_names
        self.game_run: GameRun | None = None
        self._loading = False

        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        add_action_btn = QPushButton("+ Action Node")
        add_delay_btn = QPushButton("+ Delay Node")
        add_repeat_btn = QPushButton("+ Repeat Node")
        add_compare_btn = QPushButton("+ Compare Node")
        add_find_template_btn = QPushButton("+ Find Template Node")
        add_assert_btn = QPushButton("+ Assert Node")
        delete_btn = QPushButton("Delete Selected")
        self._run_btn = QPushButton("Run")
        self._preview_btn = QPushButton("Preview (Dry Run)")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        for b in (add_action_btn, add_delay_btn, add_repeat_btn, add_compare_btn, add_find_template_btn,
                  add_assert_btn, delete_btn, self._run_btn, self._preview_btn, self._stop_btn):
            toolbar.addWidget(b)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        add_action_btn.clicked.connect(lambda: self._add_node(RunNodeKind.ACTION))
        add_delay_btn.clicked.connect(lambda: self._add_node(RunNodeKind.DELAY))
        add_repeat_btn.clicked.connect(lambda: self._add_node(RunNodeKind.REPEAT))
        add_compare_btn.clicked.connect(lambda: self._add_node(RunNodeKind.COMPARE))
        add_find_template_btn.clicked.connect(lambda: self._add_node(RunNodeKind.FIND_TEMPLATE))
        add_assert_btn.clicked.connect(lambda: self._add_node(RunNodeKind.ASSERT))
        delete_btn.clicked.connect(self._delete_selected)
        self._run_btn.clicked.connect(lambda: self.runRequested.emit(self.game_run))
        self._preview_btn.clicked.connect(lambda: self.previewRequested.emit(self.game_run))
        self._stop_btn.clicked.connect(self.stopRequested.emit)

        self._scene = RunGraphScene()
        self._scene.graphChanged.connect(self._on_graph_changed)
        self._scene.nodeSelected.connect(self._on_node_selected)
        self._view = RunGraphView(self._scene)
        layout.addWidget(self._view, stretch=3)

        props_row = QHBoxLayout()
        props_row.addWidget(QLabel("Selected node:"))
        self._node_label = QLabel("(none)")
        props_row.addWidget(self._node_label)
        self._action_combo = QComboBox()
        self._action_combo.currentTextChanged.connect(self._on_action_combo_changed)
        props_row.addWidget(self._action_combo)
        self._template_combo = QComboBox()
        self._template_combo.currentTextChanged.connect(self._on_template_combo_changed)
        props_row.addWidget(self._template_combo)
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("assertion label, e.g. cleared_gap")
        self._label_edit.editingFinished.connect(self._on_label_edited)
        props_row.addWidget(self._label_edit)
        self._value_spin = QSpinBox()
        self._value_spin.setRange(1, 100000)
        self._value_spin.valueChanged.connect(self._on_value_spin_changed)
        props_row.addWidget(self._value_spin)
        props_row.addStretch(1)
        layout.addLayout(props_row)
        self._set_props_visible(None)

        self._warnings = QLabel("")
        self._warnings.setStyleSheet("color: #c0392b;")
        self._warnings.setWordWrap(True)
        layout.addWidget(self._warnings)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setMaximumHeight(120)
        layout.addWidget(self._log)

    # -- binding --------------------------------------------------------

    def set_run(self, game_run: GameRun | None) -> None:
        self.game_run = game_run
        self._scene.load(game_run)
        self._set_props_visible(None)
        self._run_btn.setEnabled(game_run is not None)

    def log_line(self, text: str) -> None:
        self._log.appendPlainText(text)

    def set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running and self.game_run is not None)
        self._stop_btn.setEnabled(running)

    def refresh_warnings(self, project_actions: dict, project_templates: dict | None = None) -> None:
        if self.game_run is None:
            self._warnings.setText("")
            return
        warnings = self.game_run.validate(project_actions, project_templates)
        warnings += run_pointer_conflicts(self.game_run, project_actions)
        self._warnings.setText("\n".join(warnings))

    # -- toolbar actions --------------------------------------------------------

    def _add_node(self, kind: RunNodeKind) -> None:
        if self.game_run is None:
            return
        self._scene.add_node(kind)

    def _delete_selected(self) -> None:
        self._scene.remove_selected()

    def _on_graph_changed(self) -> None:
        self.graphChanged.emit()

    # -- node property panel --------------------------------------------------------

    def _set_props_visible(self, node: RunNode | None) -> None:
        self._action_combo.setVisible(node is not None and node.kind == RunNodeKind.ACTION)
        self._template_combo.setVisible(node is not None and node.kind in _TEMPLATE_KINDS)
        self._label_edit.setVisible(node is not None and node.kind == RunNodeKind.ASSERT)
        self._value_spin.setVisible(node is not None and node.kind in (RunNodeKind.DELAY, RunNodeKind.REPEAT))

    def _on_node_selected(self, node: RunNode | None) -> None:
        self._loading = True
        try:
            self._set_props_visible(node)
            if node is None:
                self._node_label.setText("(none)")
                return
            self._node_label.setText(f"{node.id} ({node.kind.value})")
            if node.kind == RunNodeKind.ACTION:
                self._action_combo.clear()
                names = self._get_action_names()
                self._action_combo.addItems([""] + names)
                self._action_combo.setCurrentText(node.action_name)
            elif node.kind in _TEMPLATE_KINDS:
                self._template_combo.clear()
                names = self._get_template_names()
                self._template_combo.addItems([""] + names)
                self._template_combo.setCurrentText(node.template_name)
                if node.kind == RunNodeKind.ASSERT:
                    self._label_edit.setText(node.label)
            elif node.kind == RunNodeKind.DELAY:
                self._value_spin.setRange(0, 100000)
                self._value_spin.setValue(node.frames)
            elif node.kind == RunNodeKind.REPEAT:
                self._value_spin.setRange(1, 100000)
                self._value_spin.setValue(node.times)
        finally:
            self._loading = False

    def _selected_node(self) -> RunNode | None:
        selected = [i for i in self._scene.selectedItems() if hasattr(i, "node")]
        return selected[0].node if len(selected) == 1 else None

    def _on_action_combo_changed(self, text: str) -> None:
        if self._loading:
            return
        node = self._selected_node()
        if node is None or node.kind != RunNodeKind.ACTION:
            return
        node.action_name = text
        self._scene._node_items[node.id].refresh_label()
        self.graphChanged.emit()

    def _on_template_combo_changed(self, text: str) -> None:
        if self._loading:
            return
        node = self._selected_node()
        if node is None or node.kind not in _TEMPLATE_KINDS:
            return
        node.template_name = text
        self._scene._node_items[node.id].refresh_label()
        self.graphChanged.emit()

    def _on_label_edited(self) -> None:
        if self._loading:
            return
        node = self._selected_node()
        if node is None or node.kind != RunNodeKind.ASSERT:
            return
        node.label = self._label_edit.text()
        self._scene._node_items[node.id].refresh_label()
        self.graphChanged.emit()

    def _on_value_spin_changed(self, value: int) -> None:
        if self._loading:
            return
        node = self._selected_node()
        if node is None:
            return
        if node.kind == RunNodeKind.DELAY:
            node.frames = value
        elif node.kind == RunNodeKind.REPEAT:
            node.times = value
        self._scene._node_items[node.id].refresh_label()
        self.graphChanged.emit()
