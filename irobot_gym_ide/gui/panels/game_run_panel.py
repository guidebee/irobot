""""Game Run" workflow tab: the list of a project's GameRuns alongside the
node-graph editor for whichever one is selected. Game Run design consumes
Actions/Templates defined elsewhere (via RunEditorWidget's Compare/Find
Template nodes), which is why those stay reachable through the always-present
Library dock rather than being confined to the Define tab.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from ..run_editor import RunEditorWidget


class GameRunPanel(QWidget):
    def __init__(self, get_action_names, get_template_names=lambda: [], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)

        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("Game Runs"))
        self.run_list = QListWidget()
        left_col.addWidget(self.run_list)
        btn_row = QHBoxLayout()
        self.add_run_btn = QPushButton("Add Run")
        self.remove_run_btn = QPushButton("Remove Run")
        btn_row.addWidget(self.add_run_btn)
        btn_row.addWidget(self.remove_run_btn)
        left_col.addLayout(btn_row)

        left_widget = QWidget()
        left_widget.setLayout(left_col)
        left_widget.setMaximumWidth(220)
        layout.addWidget(left_widget)

        self.run_editor = RunEditorWidget(get_action_names, get_template_names)
        layout.addWidget(self.run_editor, 1)
