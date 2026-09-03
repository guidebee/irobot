"""irobot Gym IDE: a desktop tool for defining per-game action maps.

Pure-Python core (model.py, io.py, connection.py) has no GUI dependency and
is usable headlessly (scripts, tests, and eventually tools/irobot_gym/env.py
all load the same project files this package's GUI edits). The GUI
(gui/main_window.py) is one client of that core, not the source of truth.

See docs/irobot_gym_ide_design.md for the design.
"""
