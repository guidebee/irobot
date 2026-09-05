"""Exports a project's Actions/HudRegions as an `ActionMap` matching
docs/opengym_implementation_plan.md §7.4's "Tier 1.5 -- named virtual-button actions" schema --
the bridge artifact between this IDE's action-definition tooling and the not-yet-built
tools/irobot_gym/env.py (see model.py's own module docstring: that package doesn't exist yet;
see ACTION_CLASSIFICATION_DESIGN.md G17). This module does not build an env or a gym.Env
subclass -- it only produces the input that plan's Tier 1.5 loader is already specified to
expect, so nothing here needs to change once that loader actually exists.

Only HudRegions become `buttons` -- Tier 1.5 is specifically about a *fixed on-screen gamepad*
with a real screen position per button, which is exactly what a HudRegion is and a bare Action
is not (an Action with no HudRegion pointing at it has no fixed position to offer, so it's
omitted from `buttons` -- still present in the project's own actions.yaml, just not part of
this particular export). A HudRegion's rectangle is approximated as its *inscribed* circle
(`radius = min(width, height) / 2`) since the plan's schema is circle-based -- a real geometric
simplification for a non-square region, not a bug; conservative (never extends outside the
original rectangle) rather than exact. `region.is_hold` (see model.HudRegion) exports
`press_modes: [tap, hold]` (this project's own hold regions already handle a quick tap as an
immediate down-then-up, matching that press mode's meaning); a plain region exports
`press_modes: [tap]` only. A hold region's *pair* of underlying Actions (`action_name`/
`release_action_name`, e.g. `right_start`/`right_stop`) collapses into the ONE `right` button
entry here, matching how Tier 1.5 itself models a hold button as one entry with two press/
release states, not two separate named actions.

`macros` holds any MACRO-kind action (`Action.effective_kind`, see model.py) that reduces to
the plan's narrow single-button/hold-duration shape (exactly one PRESS, one RELEASE, and at
least one WAIT, all on the pointer_id of exactly one exported button) -- e.g. a fixed-duration
`long_jump`. Anything MACRO-shaped but not reducible to that (multi-pointer, like `right_jump`,
which presses two different buttons' pointers) is real, useful data with no home in the plan's
current schema, so it's exported additively under `compound_macros` (not part of the linked
plan doc) with its own raw `events` list rather than silently dropped or forced into a shape
that would lose information -- a future env.py extension point, not a gap this module can close
on its own.
"""
from __future__ import annotations

from .model import Action, ActionKind, EventKind, HudRegion, Project


def _region_to_circle(region: HudRegion) -> dict:
    cx = region.x + region.width / 2
    cy = region.y + region.height / 2
    radius = min(region.width, region.height) / 2
    return {"cx": round(cx), "cy": round(cy), "radius": round(radius)}


def _pointer_id_of(action: Action) -> int:
    """The pointer_id this action's own touch-down event uses -- checks TAP as well as PRESS,
    since a plain (non-hold) button's action is typically a TAP, not a PRESS/RELEASE pair.
    Defaults to 0 (PrimitiveEvent's own default) if the action has no touch-down event at all
    (e.g. a KEY-only action), same fallback PrimitiveEvent itself uses."""
    for event in action.events:
        if event.kind in (EventKind.PRESS, EventKind.TAP):
            return event.pointer_id
    return 0


def _as_single_button_macro(action: Action, buttons: dict) -> dict | None:
    """{"button": name, "mode": "hold", "hold_duration_frames": N} if `action` is exactly one
    PRESS, at least one WAIT, and one RELEASE, all on the same pointer_id as an already-exported
    button -- the plan's §7.4 macro shape -- else None."""
    presses = [e for e in action.events if e.kind == EventKind.PRESS]
    releases = [e for e in action.events if e.kind == EventKind.RELEASE]
    waits = [e for e in action.events if e.kind == EventKind.WAIT]
    if len(presses) != 1 or len(releases) != 1 or not waits:
        return None
    pointer_id = presses[0].pointer_id
    if releases[0].pointer_id != pointer_id:
        return None
    for name, info in buttons.items():
        if info["pointer_id"] == pointer_id:
            return {"button": name, "mode": "hold", "hold_duration_frames": sum(w.frames for w in waits)}
    return None


def export_action_map(project: Project, on_log=None) -> dict:
    """Builds the ActionMap dict described in this module's own docstring. Pure function:
    reads `project`, never mutates it. `on_log`, if given, is told about anything left out of
    `buttons` (an action with no HudRegion) purely for visibility -- never an error, since a
    project legitimately has actions (a plain tap-anywhere macro, say) that aren't part of a
    fixed on-screen gamepad at all."""
    on_log = on_log or (lambda msg: None)
    buttons: dict = {}
    region_by_action_name: dict = {}
    for region in project.hud_regions.values():
        if not region.action_name:
            continue
        start_action = project.actions.get(region.action_name)
        if start_action is None:
            on_log(f"HUD region {region.name!r}: action {region.action_name!r} not found, skipped")
            continue
        buttons[region.name] = {
            "region": _region_to_circle(region),
            "pointer_id": _pointer_id_of(start_action),
            "press_modes": ["tap", "hold"] if region.is_hold else ["tap"],
        }
        region_by_action_name[region.action_name] = region.name
        if region.is_hold:
            region_by_action_name[region.release_action_name] = region.name

    exported_names = set(region_by_action_name)
    macros: dict = {}
    compound_macros: dict = {}
    for name, action in project.actions.items():
        if name in exported_names or action.effective_kind != ActionKind.MACRO:
            continue
        single = _as_single_button_macro(action, buttons)
        if single is not None:
            macros[name] = single
        else:
            compound_macros[name] = {
                "description": action.description,
                "events": [e.to_dict() for e in action.events],
            }

    unbuttoned = [
        name for name, action in project.actions.items()
        if name not in exported_names and name not in macros and name not in compound_macros
    ]
    if unbuttoned:
        on_log(f"{len(unbuttoned)} action(s) have no HudRegion and aren't part of any macro, so they're "
               f"not part of this ActionMap: {', '.join(sorted(unbuttoned))}")

    result = {
        "schema_version": 1,
        "tier": "button",
        "reference_resolution": {"width": project.reference_width, "height": project.reference_height},
        "buttons": buttons,
        "macros": macros,
    }
    if compound_macros:
        result["compound_macros"] = compound_macros
    return result
