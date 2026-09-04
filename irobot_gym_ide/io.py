"""YAML load/save for Project files.

Kept separate from model.py so model.py stays importable with zero third-
party dependencies; only this module needs PyYAML. File shape matches the
ActionMap schema sketched in docs/opengym_implementation_plan.md §7.4, so a
project saved here is meant to be loadable by tools/irobot_gym/env.py once
that package exists -- this IDE is a GUI front-end for that same schema,
not a competing one.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .model import GameplaySession, Project

PROJECT_FILENAME = "project.yaml"
SESSIONS_DIRNAME = "recordings"
SESSION_SUFFIX = ".session.yaml"


def save_project(project: Project, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(project.to_dict(), f, sort_keys=False, allow_unicode=True)


def load_project(path) -> Project:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Project.from_dict(data)


def sessions_dir(project_path) -> Path:
    """Where GameplaySessions for the project at `project_path` (its
    project.yaml file path) live -- a `recordings/` sibling directory, kept
    out of project.yaml itself since a session's raw event list can be large
    and isn't part of the ActionMap-shaped authoring schema env.py loads."""
    return Path(project_path).parent / SESSIONS_DIRNAME


def save_session(session: GameplaySession, project_path) -> Path:
    """Saves `session` into `sessions_dir(project_path)`, named after
    `session.name`, creating that directory if needed. Returns the path
    written."""
    directory = sessions_dir(project_path)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session.name}{SESSION_SUFFIX}"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(session.to_dict(), f, sort_keys=False, allow_unicode=True)
    return path


def load_session(path) -> GameplaySession:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return GameplaySession.from_dict(data)


def list_sessions(project_path) -> list:
    """Returns the paths of every saved session for the project at
    `project_path`, sorted by filename. Empty list if `recordings/` doesn't
    exist yet (no session saved for this project so far)."""
    directory = sessions_dir(project_path)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{SESSION_SUFFIX}"))
