"""Right-dock "Library": a single tree of every defined Action / HUD Region /
HUD Combo / Image Template, grouped by category. Cross-cutting reference data
like this needs to be visible regardless of which workflow tab is active --
Game Run's Compare/Find Template nodes reference Templates, and future
Reward/Observation/Reset stages will reference Actions/HUD Regions too -- so
it lives in its own always-present dock rather than being confined to one tab.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..thumbnails import decode_template_qimage

_GROUPS = [
    ("action", "Actions"),
    ("hud_region", "HUD Regions"),
    ("hud_combo", "HUD Combos"),
    ("template", "Image Templates"),
]

# Templates and HUD Regions are capture-only (no "new empty" concept) -- the
# canvas's capture-rectangle tool, triggered from the Define tab, is their
# only creation path. HUD Combos have no capture path either, but (unlike
# Templates/HUD Regions) their Add/Remove buttons are their only creation
# mechanism, so those buttons live in the Define tab instead of here -- see
# DefinePanel. That leaves only Actions addable/removable from this toolbar.
_ADDABLE_CATEGORIES = {"action"}
_REMOVABLE_CATEGORIES = {"action", "hud_region", "template"}
# Renamable: only categories another definition can reference *by name* elsewhere in the
# project (HudRegion.action_name/release_action_name, HudRegionCombo.action_name/
# region_names, RunNode.action_name) -- see ACTION_CLASSIFICATION_DESIGN.md G1. A bare
# free-text name edit would silently orphan those references, so rename goes through
# Project.rename_action/rename_hud_region instead, which cascade the update project-wide.
_RENAMABLE_CATEGORIES = {"action", "hud_region"}


class LibraryPanel(QWidget):
    selectionChanged = Signal(str, str)   # (category, name) -- ("", "") for a group header or nothing selected
    addRequested = Signal(str)            # category
    removeRequested = Signal(str, str)    # (category, name)
    renameRequested = Signal(str, str)    # (category, name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_category = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add")
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.clicked.connect(self._on_rename_clicked)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addWidget(self._rename_btn)
        layout.addLayout(btn_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._tree)

        self._group_items: dict[str, QTreeWidgetItem] = {}
        for category, label in _GROUPS:
            group_item = QTreeWidgetItem([label])
            group_item.setData(0, Qt.UserRole, (category, None))
            group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
            self._tree.addTopLevelItem(group_item)
            group_item.setExpanded(True)
            self._group_items[category] = group_item

        self._update_button_state()

    # -- refresh (called by MainWindow whenever the underlying project data changes) --

    def refresh_actions(self, names: list[str]) -> None:
        self._refresh_group("action", [(name, None) for name in names])

    def refresh_hud_regions(self, names: list[str]) -> None:
        self._refresh_group("hud_region", [(name, None) for name in names])

    def refresh_hud_combos(self, names: list[str]) -> None:
        self._refresh_group("hud_combo", [(name, None) for name in names])

    def refresh_templates(self, templates: dict) -> None:
        icons = []
        for name, template in templates.items():
            image = decode_template_qimage(template)
            icon = QIcon(QPixmap.fromImage(image)) if image is not None else None
            icons.append((name, icon))
        self._refresh_group("template", icons)

    def _refresh_group(self, category: str, entries: list[tuple[str, "QIcon | None"]]) -> None:
        group_item = self._group_items[category]
        group_item.takeChildren()   # if the current selection lived here, Qt fires currentItemChanged(None, ...) for us
        for name, icon in entries:
            leaf = QTreeWidgetItem([name])
            leaf.setData(0, Qt.UserRole, (category, name))
            if icon is not None:
                leaf.setIcon(0, icon)
            group_item.addChild(leaf)

    # -- selection / add / remove --

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self._current_category = ""
            self.selectionChanged.emit("", "")
        else:
            category, name = current.data(0, Qt.UserRole)
            self._current_category = category
            if name is None:
                self.selectionChanged.emit("", "")   # group header selected -- nothing concrete to show
            else:
                self.selectionChanged.emit(category, name)
        self._update_button_state()

    def _update_button_state(self) -> None:
        current = self._tree.currentItem()
        is_leaf = bool(current and current.data(0, Qt.UserRole)[1] is not None)
        self._add_btn.setEnabled(self._current_category in _ADDABLE_CATEGORIES)
        self._remove_btn.setEnabled(is_leaf and self._current_category in _REMOVABLE_CATEGORIES)
        self._rename_btn.setEnabled(is_leaf and self._current_category in _RENAMABLE_CATEGORIES)

    def _on_add_clicked(self) -> None:
        if self._current_category in _ADDABLE_CATEGORIES:
            self.addRequested.emit(self._current_category)

    def _on_remove_clicked(self) -> None:
        current = self._tree.currentItem()
        if current is None:
            return
        category, name = current.data(0, Qt.UserRole)
        if name is not None and category in _REMOVABLE_CATEGORIES:
            self.removeRequested.emit(category, name)

    def _on_rename_clicked(self) -> None:
        current = self._tree.currentItem()
        if current is None:
            return
        category, name = current.data(0, Qt.UserRole)
        if name is not None and category in _RENAMABLE_CATEGORIES:
            self.renameRequested.emit(category, name)
