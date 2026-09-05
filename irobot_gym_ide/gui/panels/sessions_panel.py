""""Sessions" workflow tab: record a whole playthrough as raw gesture events,
then classify it into Actions using HUD Regions/Combos, or replay it back.

A dumb widget-holder like DefinePanel -- MainWindow owns all the actual
recording/classification/replay logic and just wires up these widgets.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QSpinBox, QVBoxLayout, QWidget


class SessionsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Gameplay Sessions (record a whole playthrough as raw events, for later\n"
            "classification into actions -- see recordings/*.session.yaml):"))
        self.record_session_btn = QPushButton("Record Gameplay Session")
        layout.addWidget(self.record_session_btn)

        self.session_list = QListWidget()
        layout.addWidget(self.session_list)

        tolerance_row = QHBoxLayout()
        tolerance_row.addWidget(QLabel(
            "Action match tolerance (px) -- how close a gesture must land to an existing "
            "action's own recorded position to count as a match (see ACTION_CLASSIFICATION_DESIGN.md G8):"))
        self.match_tolerance_spin = QSpinBox()
        self.match_tolerance_spin.setRange(1, 500)
        self.match_tolerance_spin.setValue(30)
        tolerance_row.addWidget(self.match_tolerance_spin)
        layout.addLayout(tolerance_row)

        btn_row = QHBoxLayout()
        self.classify_session_btn = QPushButton("Classify Session")
        self.replay_raw_btn = QPushButton("Replay Raw")
        self.replay_classified_btn = QPushButton("Replay Classified")
        self.stop_replay_btn = QPushButton("Stop Replay")
        btn_row.addWidget(self.classify_session_btn)
        btn_row.addWidget(self.replay_raw_btn)
        btn_row.addWidget(self.replay_classified_btn)
        btn_row.addWidget(self.stop_replay_btn)
        layout.addLayout(btn_row)
