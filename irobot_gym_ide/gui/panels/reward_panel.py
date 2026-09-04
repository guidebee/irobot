""""Rewards" workflow tab -- placeholder. Reward definition (how a GameRun's
outcome or HUD/Template state maps to a scalar reward) is not implemented yet;
see docs/opengym_implementation_plan.md. This stub exists so the tab layout
is already in place for that future work without touching main_window.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget


class RewardPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel("Reward definition -- coming soon")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 1)
        placeholder = QListWidget()
        placeholder.setEnabled(False)
        layout.addWidget(placeholder)
