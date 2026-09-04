"""YAML load/save for Project files.

Kept separate from model.py so model.py stays importable with zero third-
party dependencies; only this module needs PyYAML. File shape matches the
ActionMap schema sketched in docs/opengym_implementation_plan.md §7.4, so a
project saved here is meant to be loadable by tools/irobot_gym/env.py once
that package exists -- this IDE is a GUI front-end for that same schema,
not a competing one.

Each project lives in its own directory, split across section files so
large blobs (template pixels) and independently-edited concerns (actions,
HUD, runs) don't all churn the same file on every save:

    <project_dir>/
        project.yaml    # meta + connection: schema_version, id, name,
                         # description, timestamps, package/activity/serial,
                         # host, port, reference_resolution
        actions.yaml    # {actions: [...]}
        templates.yaml  # {templates: [...]}
        hud.yaml        # {hud_regions: [...], hud_region_combos: [...]}
        runs.yaml       # {runs: [...]}
        recordings/     # GameplaySessions -- see sessions_dir() below

`path` in save_project/load_project is always the project.yaml path; the
project directory is its parent. Keeping project.yaml as the addressed file
(rather than the directory) is what lets recordings stay naturally scoped
per-project: sessions_dir() derives from that same parent.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .model import GameplaySession, Project

PROJECT_FILENAME = "project.yaml"
ACTIONS_FILENAME = "actions.yaml"
TEMPLATES_FILENAME = "templates.yaml"
HUD_FILENAME = "hud.yaml"
RUNS_FILENAME = "runs.yaml"
SESSIONS_DIRNAME = "recordings"
SESSION_SUFFIX = ".session.yaml"

_META_KEYS = (
    "schema_version", "id", "name", "description", "created_at", "updated_at",
    "package", "activity", "serial", "host", "port", "reference_resolution",
)


def save_project(project: Project, path) -> None:
    """Writes `project` as project.yaml plus its section files, alongside
    `path`. Creates the project directory if it doesn't exist yet."""
    project_dir = Path(path).parent
    project_dir.mkdir(parents=True, exist_ok=True)
    full = project.to_dict()

    meta = {k: full[k] for k in _META_KEYS}
    _dump(project_dir / PROJECT_FILENAME, meta)
    _dump(project_dir / ACTIONS_FILENAME, {"actions": full["actions"]})
    _dump(project_dir / TEMPLATES_FILENAME, {"templates": full["templates"]})
    _dump(project_dir / HUD_FILENAME, {
        "hud_regions": full["hud_regions"],
        "hud_region_combos": full["hud_region_combos"],
    })
    _dump(project_dir / RUNS_FILENAME, {"runs": full["runs"]})


def load_project(path) -> Project:
    """Loads the project whose project.yaml is at `path`, merging in its
    sibling section files (each optional, so a hand-created project.yaml
    with no actions.yaml/etc. yet still loads fine)."""
    project_dir = Path(path).parent
    data = _load(path) or {}
    data.setdefault("actions", []).extend(_load_section(project_dir / ACTIONS_FILENAME, "actions"))
    data.setdefault("templates", []).extend(_load_section(project_dir / TEMPLATES_FILENAME, "templates"))
    data.setdefault("hud_regions", []).extend(_load_section(project_dir / HUD_FILENAME, "hud_regions"))
    data.setdefault("hud_region_combos", []).extend(_load_section(project_dir / HUD_FILENAME, "hud_region_combos"))
    data.setdefault("runs", []).extend(_load_section(project_dir / RUNS_FILENAME, "runs"))
    return Project.from_dict(data)


def migrate_legacy_project(old_path, new_project_dir) -> Path:
    """Converts a pre-split single-file project (schema_version 1, one flat
    <name>.yaml with everything inline) into the new per-directory, split-file
    layout. Returns the path to the new project.yaml. Does not touch or move
    any recordings -- the old shared recordings/ directory may hold sessions
    belonging to other projects too, so callers move/copy those explicitly."""
    project = load_project(old_path)
    new_path = Path(new_project_dir) / PROJECT_FILENAME
    save_project(project, new_path)
    return new_path


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


def _dump(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _load(path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_section(path: Path, key: str) -> list:
    if not path.is_file():
        return []
    data = _load(path) or {}
    return data.get(key, [])
