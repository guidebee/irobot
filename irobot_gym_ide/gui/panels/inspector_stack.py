"""Right-dock "Inspector": a stacked widget showing whichever detail editor
matches the current Library selection (Action / Template / HUD Region / HUD
Combo), or an empty-state placeholder when nothing is selected."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedWidget

from ...model import Action, HudRegion, HudRegionCombo, ImageTemplate
from ..inspector import ActionInspector
from .detail_inspectors import HudComboInspector, HudRegionInspector, TemplateInspector


class InspectorStack(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._empty_label = QLabel("(nothing selected)")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self.addWidget(self._empty_label)

        self.action_inspector = ActionInspector()
        self.addWidget(self.action_inspector)

        self.template_inspector = TemplateInspector()
        self.addWidget(self.template_inspector)

        self.hud_region_inspector = HudRegionInspector()
        self.addWidget(self.hud_region_inspector)

        self.hud_combo_inspector = HudComboInspector()
        self.addWidget(self.hud_combo_inspector)

    def show_nothing(self) -> None:
        self.setCurrentWidget(self._empty_label)

    def show_action(self, action: Action | None) -> None:
        self.action_inspector.set_action(action)
        self.setCurrentWidget(self.action_inspector)

    def show_template(self, template: ImageTemplate | None) -> None:
        self.template_inspector.set_template(template)
        self.setCurrentWidget(self.template_inspector)

    def show_hud_region(self, region: HudRegion | None) -> None:
        self.hud_region_inspector.set_hud_region(region)
        self.setCurrentWidget(self.hud_region_inspector)

    def set_region_choices(self, names: list[str]) -> None:
        self.hud_combo_inspector.set_region_choices(names)

    def show_hud_combo(self, combo: HudRegionCombo | None) -> None:
        self.hud_combo_inspector.set_combo(combo)
        self.setCurrentWidget(self.hud_combo_inspector)
