"""Property editor for the currently-selected Action's event sequence.

A plain editable table rather than a fancier property-grid widget --
matches the "start simple, single events combined into actions" scope: add
an event (from a canvas click or the Add Key/Wait buttons), edit its fields
inline, reorder/delete, done.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QComboBox, QPushButton, QLabel, QSpinBox, QLineEdit,
)

from ..model import Action, EventKind, PrimitiveEvent

_COLUMNS = ["kind", "pointer_id", "x", "y", "keycode/key_name", "frames"]


class ActionInspector(QWidget):
    actionChanged = Signal()   # emitted whenever the in-place edit mutates the action's events

    def __init__(self, parent=None):
        super().__init__(parent)
        self._action: Action | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        self._title = QLabel("(no action selected)")
        layout.addWidget(self._title)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

        button_row = QHBoxLayout()
        self._add_key_btn = QPushButton("Add Key Event")
        self._add_wait_btn = QPushButton("Add Wait")
        self._remove_btn = QPushButton("Remove Selected")
        self._up_btn = QPushButton("Move Up")
        self._down_btn = QPushButton("Move Down")
        for b in (self._add_key_btn, self._add_wait_btn, self._remove_btn, self._up_btn, self._down_btn):
            button_row.addWidget(b)
        layout.addLayout(button_row)

        self._add_key_btn.clicked.connect(self._add_key_event)
        self._add_wait_btn.clicked.connect(self._add_wait_event)
        self._remove_btn.clicked.connect(self._remove_selected)
        self._up_btn.clicked.connect(lambda: self._move_selected(-1))
        self._down_btn.clicked.connect(lambda: self._move_selected(1))

        self._warnings = QLabel("")
        self._warnings.setStyleSheet("color: #c0392b;")
        self._warnings.setWordWrap(True)
        layout.addWidget(self._warnings)

    # -- binding --------------------------------------------------------

    def set_action(self, action: Action | None) -> None:
        self._action = action
        self._title.setText(f"Action: {action.name}" if action else "(no action selected)")
        self._reload_table()

    def add_event_at_point(self, x: int, y: int, kind: EventKind, pointer_id: int) -> PrimitiveEvent | None:
        if self._action is None:
            return None
        event = PrimitiveEvent(kind=kind, pointer_id=pointer_id, x=x, y=y)
        self._action.events.append(event)
        self._reload_table()
        self.actionChanged.emit()
        return event

    def _add_key_event(self) -> None:
        if self._action is None:
            return
        self._action.events.append(PrimitiveEvent(kind=EventKind.KEY, key_name="back"))
        self._reload_table()
        self.actionChanged.emit()

    def _add_wait_event(self) -> None:
        if self._action is None:
            return
        self._action.events.append(PrimitiveEvent(kind=EventKind.WAIT, frames=10))
        self._reload_table()
        self.actionChanged.emit()

    def _remove_selected(self) -> None:
        if self._action is None:
            return
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            del self._action.events[row]
        self._reload_table()
        self.actionChanged.emit()

    def _move_selected(self, delta: int) -> None:
        if self._action is None:
            return
        rows = sorted({i.row() for i in self._table.selectedIndexes()})
        events = self._action.events
        for row in (rows if delta < 0 else reversed(rows)):
            new_row = row + delta
            if 0 <= new_row < len(events):
                events[row], events[new_row] = events[new_row], events[row]
        self._reload_table()
        self.actionChanged.emit()

    # -- table sync --------------------------------------------------------

    def _reload_table(self) -> None:
        self._loading = True
        self._table.setRowCount(0)
        if self._action is not None:
            for event in self._action.events:
                self._append_row(event)
            self._warnings.setText("\n".join(self._action.validate()))
        else:
            self._warnings.setText("")
        self._loading = False

    def _append_row(self, event: PrimitiveEvent) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        combo = QComboBox()
        combo.addItems([k.value for k in EventKind])
        combo.setCurrentText(event.kind.value)
        combo.currentTextChanged.connect(lambda _text, r=row: self._on_kind_changed(r))
        self._table.setCellWidget(row, 0, combo)

        self._table.setItem(row, 1, QTableWidgetItem(str(event.pointer_id)))
        self._table.setItem(row, 2, QTableWidgetItem("" if event.x is None else str(event.x)))
        self._table.setItem(row, 3, QTableWidgetItem("" if event.y is None else str(event.y)))
        key_field = event.key_name or ("" if event.keycode is None else str(event.keycode))
        self._table.setItem(row, 4, QTableWidgetItem(key_field))
        self._table.setItem(row, 5, QTableWidgetItem(str(event.frames)))

    def _on_kind_changed(self, row: int) -> None:
        if self._loading or self._action is None:
            return
        combo = self._table.cellWidget(row, 0)
        self._action.events[row].kind = EventKind(combo.currentText())
        self._warnings.setText("\n".join(self._action.validate()))
        self.actionChanged.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self._action is None:
            return
        row, col = item.row(), item.column()
        event = self._action.events[row]
        text = item.text().strip()
        try:
            if col == 1:
                event.pointer_id = int(text or 0)
            elif col == 2:
                event.x = int(text) if text else None
            elif col == 3:
                event.y = int(text) if text else None
            elif col == 4:
                if text.isdigit():
                    event.keycode, event.key_name = int(text), None
                else:
                    event.keycode, event.key_name = None, (text or None)
            elif col == 5:
                event.frames = int(text or 0)
        except ValueError:
            pass  # leave the model value as-is; the cell text is what the user typed, will re-validate on next reload
        self._warnings.setText("\n".join(self._action.validate()))
        self.actionChanged.emit()
