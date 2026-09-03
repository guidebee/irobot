"""YAML load/save for Project files.

Kept separate from model.py so model.py stays importable with zero third-
party dependencies; only this module needs PyYAML. File shape matches the
ActionMap schema sketched in docs/opengym_implementation_plan.md §7.4, so a
project saved here is meant to be loadable by tools/irobot_gym/env.py once
that package exists -- this IDE is a GUI front-end for that same schema,
not a competing one.
"""
from __future__ import annotations

import yaml

from .model import Project

PROJECT_FILENAME = "project.yaml"


def save_project(project: Project, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(project.to_dict(), f, sort_keys=False, allow_unicode=True)


def load_project(path) -> Project:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Project.from_dict(data)
