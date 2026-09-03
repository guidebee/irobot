#!/usr/bin/env python3
"""Entry point: python -m irobot_gym_ide.app (from tools/) or
python -m tools.irobot_gym_ide.app (from the repo root, if tools/ has been
made a package). See docs/irobot_gym_ide_design.md for setup/usage."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
