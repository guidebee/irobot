""""Define" workflow tab: the trigger controls for creating Actions, Image
Templates, HUD Regions, and HUD Combos. The actual lists of these entities
live in the Library dock (visible from every tab); the actual editable detail
fields live in the Inspector dock -- this tab only holds buttons/controls that
*create* or *arm capture for* an entity, per the "no duplicate editable
fields" rule (see the redesign plan's Design decisions section).

A dumb widget-holder with no Project/connection reference of its own -- like
ActionInspector and RunEditorWidget, it exposes its buttons/controls as
public attributes for MainWindow to wire up.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ...model import EventKind


class DefinePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # -- Actions --------------------------------------------------------
        layout.addWidget(QLabel("New event on canvas click:"))
        click_row = QHBoxLayout()
        self.new_kind_combo = QComboBox()
        self.new_kind_combo.addItems([EventKind.TAP.value, EventKind.PRESS.value, EventKind.MOVE.value])
        self.new_pointer_spin = QSpinBox()
        self.new_pointer_spin.setRange(0, 9)
        click_row.addWidget(self.new_kind_combo)
        click_row.addWidget(self.new_pointer_spin)
        layout.addLayout(click_row)

        self.live_send_checkbox = QCheckBox("Send new events live as you click (recommended)")
        self.live_send_checkbox.setChecked(True)
        layout.addWidget(self.live_send_checkbox)

        self.test_action_btn = QPushButton("Test Action (send live)")
        layout.addWidget(self.test_action_btn)
        self.release_btn = QPushButton("Release All Held Pointers")
        layout.addWidget(self.release_btn)

        layout.addWidget(QLabel("Record real touches directly on the device (bypasses the mirror):"))
        self.record_device_btn = QPushButton("Record from Device")
        layout.addWidget(self.record_device_btn)

        # -- Image Templates --------------------------------------------------------
        layout.addWidget(QLabel("Image Templates (for Game Run Compare / Find Template nodes):"))
        self.capture_region_btn = QPushButton("Capture Region")
        self.capture_region_btn.setCheckable(True)
        layout.addWidget(self.capture_region_btn)

        # -- HUD Regions --------------------------------------------------------
        layout.addWidget(QLabel(
            "HUD Regions (fixed on-screen buttons -- classifies a gameplay session's\n"
            "gestures by where they landed; see hud_classifier.py):"))
        self.capture_hud_region_btn = QPushButton("Capture HUD Region")
        self.capture_hud_region_btn.setCheckable(True)
        layout.addWidget(self.capture_hud_region_btn)

        # -- HUD Combos --------------------------------------------------------
        layout.addWidget(QLabel(
            "HUD Combos (2+ regions touched together -> one action, e.g.\n"
            "right_button + jump_button -> right_jump). No capture path -- Add/Remove\n"
            "here are their only creation mechanism; edit membership in the Inspector dock:"))
        combo_btn_row = QHBoxLayout()
        self.add_combo_btn = QPushButton("Add Combo")
        self.remove_combo_btn = QPushButton("Remove Combo")
        combo_btn_row.addWidget(self.add_combo_btn)
        combo_btn_row.addWidget(self.remove_combo_btn)
        layout.addLayout(combo_btn_row)

        # -- Gym export --------------------------------------------------------
        layout.addWidget(QLabel(
            "Export this project's HUD-region buttons/macros as an ActionMap for the\n"
            "not-yet-built Gym env (docs/opengym_implementation_plan.md §7.4):"))
        self.export_action_map_btn = QPushButton("Export Action Map...")
        layout.addWidget(self.export_action_map_btn)

        layout.addStretch(1)
