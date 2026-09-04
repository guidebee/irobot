""""Observations" workflow tab -- placeholder. Observation-space definition
(which HUD Regions/Templates/values become part of a Gym env's observation)
is not implemented yet; see docs/opengym_implementation_plan.md. This stub
exists so the tab layout is already in place for that future work without
touching main_window.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget


class ObservationPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel("Observation definition -- coming soon")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 1)
        placeholder = QListWidget()
        placeholder.setEnabled(False)
        layout.addWidget(placeholder)
