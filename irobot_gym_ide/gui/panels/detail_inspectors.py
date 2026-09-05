"""Context-specific detail editors shown by InspectorStack for whatever is
selected in the Library dock: a Template's preview+threshold, a HUD Region's
rect+action-name, or a HUD Combo's region-membership+action-name.

Each follows the same `_loading_*` guard-flag convention MainWindow already
used for this (see its historical `_loading_template_fields` etc.): while a
`set_*` call is populating widgets programmatically, an editingFinished/
valueChanged signal fired by that same populate must be a no-op, or it would
read back partially-set widgets and clobber the model object being loaded.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QWidget,
)

from ...model import HudRegion, HudRegionCombo, ImageTemplate
from ..thumbnails import decode_template_qimage


class TemplateInspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._template: ImageTemplate | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        self._preview = QLabel()
        self._preview.setFixedHeight(60)
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setStyleSheet("border: 1px solid #888;")
        layout.addWidget(self._preview)

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Match threshold"))
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.0, 1.0)
        self._threshold_spin.setSingleStep(0.01)
        self._threshold_spin.setDecimals(2)
        self._threshold_spin.valueChanged.connect(self._on_threshold_changed)
        threshold_row.addWidget(self._threshold_spin)
        threshold_row.addStretch(1)
        layout.addLayout(threshold_row)
        layout.addStretch(1)

    def set_template(self, template: ImageTemplate | None) -> None:
        self._template = template
        self._loading = True
        try:
            self._threshold_spin.setValue(template.threshold if template else 0.9)
        finally:
            self._loading = False
        image = decode_template_qimage(template) if template else None
        if image is not None:
            self._preview.setPixmap(QPixmap.fromImage(image).scaledToHeight(60, Qt.SmoothTransformation))
        else:
            self._preview.clear()

    def _on_threshold_changed(self, value: float) -> None:
        if self._loading or self._template is None:
            return
        self._template.threshold = value


class HudRegionInspector(QWidget):
    regionEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._region: HudRegion | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._action_edit = QLineEdit()
        self._action_edit.editingFinished.connect(self._on_action_edited)
        form.addRow("Action name", self._action_edit)

        self._release_action_edit = QLineEdit()
        self._release_action_edit.setPlaceholderText("(leave blank for a one-shot tap region)")
        self._release_action_edit.editingFinished.connect(self._on_release_action_edited)
        form.addRow("Release action name (hold regions)", self._release_action_edit)

        self._x_spin = QSpinBox(); self._x_spin.setRange(0, 100000)
        self._y_spin = QSpinBox(); self._y_spin.setRange(0, 100000)
        self._w_spin = QSpinBox(); self._w_spin.setRange(0, 100000)
        self._h_spin = QSpinBox(); self._h_spin.setRange(0, 100000)
        for spin in (self._x_spin, self._y_spin, self._w_spin, self._h_spin):
            spin.valueChanged.connect(self._on_rect_edited)
        form.addRow("X", self._x_spin)
        form.addRow("Y", self._y_spin)
        form.addRow("Width", self._w_spin)
        form.addRow("Height", self._h_spin)

        layout.addLayout(form)
        layout.addStretch(1)

    def set_hud_region(self, region: HudRegion | None) -> None:
        self._region = region
        self._loading = True
        try:
            self._action_edit.setText(region.action_name if region else "")
            self._release_action_edit.setText(region.release_action_name if region else "")
            self._x_spin.setValue(region.x if region else 0)
            self._y_spin.setValue(region.y if region else 0)
            self._w_spin.setValue(region.width if region else 0)
            self._h_spin.setValue(region.height if region else 0)
        finally:
            self._loading = False

    def _on_action_edited(self) -> None:
        if self._loading or self._region is None:
            return
        self._region.action_name = self._action_edit.text()

    def _on_release_action_edited(self) -> None:
        if self._loading or self._region is None:
            return
        self._region.release_action_name = self._release_action_edit.text()

    def _on_rect_edited(self, _value: int) -> None:
        if self._loading or self._region is None:
            return
        self._region.x = self._x_spin.value()
        self._region.y = self._y_spin.value()
        self._region.width = self._w_spin.value()
        self._region.height = self._h_spin.value()
        self.regionEdited.emit()


class HudComboInspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._combo: HudRegionCombo | None = None
        self._loading = False

        layout = QVBoxLayout(self)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Action name"))
        self._action_edit = QLineEdit()
        self._action_edit.editingFinished.connect(self._on_action_edited)
        action_row.addWidget(self._action_edit)
        layout.addLayout(action_row)

        layout.addWidget(QLabel("Regions in combo (ctrl/shift-click to select 2+):"))
        self._regions_list = QListWidget()
        self._regions_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._regions_list.itemSelectionChanged.connect(self._on_regions_changed)
        layout.addWidget(self._regions_list)

    def set_region_choices(self, names: list[str]) -> None:
        self._regions_list.clear()
        for name in names:
            self._regions_list.addItem(QListWidgetItem(name))
        self._sync_region_selection()

    def set_combo(self, combo: HudRegionCombo | None) -> None:
        self._combo = combo
        self._loading = True
        try:
            self._action_edit.setText(combo.action_name if combo else "")
        finally:
            self._loading = False
        self._sync_region_selection()

    def _sync_region_selection(self) -> None:
        self._loading = True
        try:
            selected_names = set(self._combo.region_names) if self._combo else set()
            for i in range(self._regions_list.count()):
                item = self._regions_list.item(i)
                item.setSelected(item.text() in selected_names)
        finally:
            self._loading = False

    def _on_regions_changed(self) -> None:
        if self._loading or self._combo is None:
            return
        self._combo.region_names = [
            self._regions_list.item(i).text()
            for i in range(self._regions_list.count())
            if self._regions_list.item(i).isSelected()
        ]

    def _on_action_edited(self) -> None:
        if self._loading or self._combo is None:
            return
        self._combo.action_name = self._action_edit.text()
