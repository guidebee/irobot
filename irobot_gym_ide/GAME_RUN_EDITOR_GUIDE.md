# Game Run Editor — User Guide

The **Game Run** tab is a node-graph editor for scripting a sequence of already-defined
Actions — including branches that run at the same time, loops, "does the screen currently look
like X" conditions, and "where on screen is X" lookups — then running that graph against a
live, connected `irobot` device. This guide covers everything in that tab: the five node types,
how connections work, capturing Image Templates, running/stopping a graph, reading its log and
warnings, and the underlying `project.yaml` file format for anyone who wants to hand-edit a
run instead of (or in addition to) dragging nodes around.

It assumes you already know how to define **Actions** in the Mirror/Actions tab (the left
panel's Actions list, the click-to-add-event canvas loop) — a Game Run is built *on top of*
actions you've already named there. See the main [`README.md`](README.md) for that part.

## Contents

1. [Before you start](#1-before-you-start)
2. [Opening / creating a run](#2-opening--creating-a-run)
3. [The canvas: adding, moving, connecting, deleting nodes](#3-the-canvas-adding-moving-connecting-deleting-nodes)
4. [Node types](#4-node-types)
5. [Image Templates: capturing a region and setting a threshold](#5-image-templates-capturing-a-region-and-setting-a-threshold)
6. [Wiring a graph: sequence, parallel, joins](#6-wiring-a-graph-sequence-parallel-joins)
7. [Running a graph and reading its log](#7-running-a-graph-and-reading-its-log)
8. [Validation warnings reference](#8-validation-warnings-reference)
9. [The `project.yaml` file format for a run](#9-the-projectyaml-file-format-for-a-run)
10. [Worked examples](#10-worked-examples)
11. [Tips and troubleshooting](#11-tips-and-troubleshooting)
12. [Known limitations](#12-known-limitations)

---

## 1. Before you start

A Game Run needs three things to actually *run* against a device (you can build and save the
graph itself without any of these):

- **At least one Action defined** in the left panel's Actions list — an empty project has
  nothing for an Action node to point at.
- **A live connection** — click **Connect** in the left panel. The Run button sends real touch
  events over the same two agent ports the Mirror/Actions tab's Test button uses.
- **Reference width/height set** — the project fields near the top of the left panel. Every
  touch event's coordinates are meaningless without this (see the Mirror/Actions tab's own
  warnings about it), and a Compare node also needs it to know how to scale a captured region
  onto the live frame's own (possibly different) pixel size — a Find Template node needs it for
  the same reason, plus to convert the position it finds back into reference coordinates.

None of this blocks *editing* — you can add nodes, wire them up, and save the project with no
device connected at all. It only blocks clicking **Run**.

## 2. Opening / creating a run

A project can hold more than one named Game Run (e.g. one for "get past the tutorial", another
for "farm resources"). In the left panel:

- **Game Runs** list — click a name to open it in the Game Run tab's canvas.
- **Add Run** — prompts for a name and creates an empty graph.
- **Remove Run** — deletes the currently-selected run (including its whole graph — this is not
  reversible from within the app; save a backup copy of `project.yaml` first if you're unsure).

Switch to the **Game Run** tab (next to **Mirror / Actions**) to see the canvas for whichever
run is currently selected.

## 3. The canvas: adding, moving, connecting, deleting nodes

The toolbar across the top of the Game Run tab:

| Button | Effect |
|---|---|
| **+ Action Node** | Adds a node that runs one named Action. |
| **+ Delay Node** | Adds a node that waits N frames. |
| **+ Repeat Node** | Adds a node that loops a subgraph a fixed number of times. |
| **+ Compare Node** | Adds a node that checks the live frame against a captured template and branches on the result. |
| **+ Find Template Node** | Adds a node that searches the whole live frame for a captured template and branches on whether it was found, stashing its (x, y) if so. |
| **Delete Selected** | Deletes every currently-selected node and edge. |
| **Run** / **Stop** | Executes the graph against the connected device / requests it stop. |

**New nodes always appear stacked at the same spot** near the top-left of the canvas (they
don't auto-space themselves) — after adding several in a row, drag them apart before wiring
anything up, or you'll be dragging one node out from underneath another.

- **Move a node**: click its body and drag.
- **Select a node or edge**: click it — it highlights (an edge turns red).
- **Select several at once**: drag a rubber-band box over empty canvas.
- **Connect two nodes**: press down on a small circle (a *port*) on the right edge of a node
  and drag to a circle on the *left* edge of another node, then release. A dashed red line
  follows your drag until you drop it on a valid target.
- **Delete**: select node(s)/edge(s), then either click **Delete Selected** or press
  **Delete**/**Backspace**. Deleting a node also deletes every edge attached to it.

Every node has exactly one input port (the circle on its left edge, labeled "in" internally —
there's no visible label, just the circle). How many *output* ports it has, and what they're
for, depends on its kind — see the next section.

### The node property panel

Below the canvas, a row shows the currently-selected node's id and kind (e.g. `a1b2c3d4
(action)`) plus whatever control edits that kind's one meaningful field:

- **Action** node → a dropdown of every action name defined in the project (plus a blank
  option meaning "not set yet").
- **Compare** node → a dropdown of every Image Template captured in the project (see
  §5), same blank-option convention.
- **Find Template** node → the same Image Template dropdown as Compare.
- **Delay** node → a spin box, 0–100000 (frames).
- **Repeat** node → a spin box, 1–100000 (iteration count).

Select nothing, or select more than one node at once, and this row hides its controls — edit
one node at a time.

## 4. Node types

Each node kind is drawn in its own color so you can tell them apart on the canvas at a glance.

### Action — blue

Runs one already-defined Action's full event sequence (its taps/presses/releases/keys/waits,
in order) against the live device, then continues. Pick which action via the property panel's
dropdown. Label on the node reads `action` / `[action_name]` (or `(pick action)` if unset).

One input port, one output port (**out**).

### Delay — gray

Waits a fixed number of frames (same unit as an Action's own `wait` event — see
[`connection.py`](connection.py)'s `FRAME_MS`), sends no wire message, then continues. Set the
frame count in the property panel. Label reads `delay` / `Nf`.

One input port, one output port (**out**).

### Repeat — orange

Not a simple pass-through: it has **two** output ports, **body** and **after**.

- Connect **body** to whatever node should start the loop. That node (and everything
  reachable from it, forming its own little subgraph) runs to completion, then runs again from
  the start, `times` times total.
- Connect **after** (optional) to whatever should run once, after all iterations finish.
- The body can itself contain forks/joins, another Repeat, or a Compare node — it's a full
  subgraph, not a single node.

Label reads `repeat` / `xN`. Set `N` (≥ 1) in the property panel.

If you don't connect **body** at all, the repeat is a no-op that just logs a warning and moves
on (see §7's log message reference).

### Compare — purple

Also has two output ports, but they mean *either/or*, not *loop*: **match** and **no_match**.

When a Compare node fires, it:

1. Looks up the Compare Template picked in the property panel (see §5).
2. Crops the *current* live frame to that template's captured region (scaled from the
   project's reference resolution onto whatever pixel size the live mirror happens to be at
   that moment).
3. Compares the crop to the template's stored pixels and computes a similarity score from 0
   (nothing alike) to 1 (identical).
4. If similarity ≥ the template's **match threshold**, follows the **match** edge; otherwise
   follows the **no_match** edge. Only one of the two fires — this is an if/else branch, not a
   fork.

Label reads `compare` / `[template_name]` (or `(pick template)` if unset). See §7 for exactly
what gets logged when it runs, including the numeric similarity score — handy for tuning a
threshold that's triggering too eagerly or not eagerly enough.

If no live frame has arrived yet, or the picked template doesn't exist (e.g. you deleted it
after wiring the node up), the node logs why and treats it as **no_match** rather than
raising an error or hanging the run.

### Find Template — teal

Compare's "where is it" sibling. Also has two output ports that mean either/or: **found** and
**not_found**. Where Compare only ever checks its template's own fixed captured region, Find
Template searches the *entire* live frame for the best-matching spot — useful for something
that moves (a coin, an enemy, a draggable piece) rather than a fixed HUD element.

When a Find Template node fires, it:

1. Looks up the Image Template picked in the property panel (same list Compare uses, see §5).
2. Slides that template's captured region size across the whole live frame, computing a
   similarity score at each position (a coarse pass first, then a fine pass around the best
   coarse spot, so the result isn't limited to a coarse search grid).
3. If the best similarity ≥ the template's **match threshold**, follows the **found** edge and
   remembers that position; otherwise follows the **not_found** edge. Only one of the two
   fires — same if/else-branch spirit as Compare, not a fork.

The (x, y) of the best match — in the project's reference resolution, same convention as an
Action's touch coordinates — is kept for the run (keyed by the node's id) so other tooling
driving a run programmatically can read back *where* the template turned up, not just whether
it did; the canvas itself doesn't currently expose a way to feed that position into a
downstream Action node (see §12).

Label reads `find_template` / `[template_name]` (or `(pick template)` if unset). See §7 for
exactly what gets logged when it runs, including the matched position and similarity score.

If no live frame has arrived yet, the picked template doesn't exist, or the template's region
no longer fits inside the live frame at all, the node logs why and treats it as **not_found**
rather than raising an error or hanging the run.

## 5. Image Templates: capturing a region and setting a threshold

Before a Compare or Find Template node has anything to compare against, you need at least one
**Image Template** — a small reference image cropped from the live mirror, tied to a
threshold. This lives in the left panel, under **Image Templates (for Game Run Compare / Find
Template nodes)**, and is managed from the **Mirror / Actions** tab (it needs the live mirror,
not the graph canvas).

To capture one:

1. Make sure you're connected (**Connect** button) and a frame is showing in the mirror.
2. Click **Capture Region** — its label changes to "Click-drag on the frame to select..." and
   the cursor becomes a crosshair over the mirror.
3. Click-drag a rectangle over whatever you want to recognize later (a game-over banner, a
   full/empty health bar, a specific button's icon, a score digit) and release. Dragging less
   than 4 pixels in either direction is treated as an accidental click and ignored, not a
   capture.
4. You'll be prompted for a name — this is what shows up in a Compare or Find Template node's
   dropdown, so name it for what it *means* (`game_over_banner`, `hp_bar_full`), not where it
   happens to sit on screen.
5. The new template appears in the **Image Templates** list with a thumbnail preview.

Select a template in that list to see its thumbnail and adjust its **Match threshold** (0.00
–1.00, default 0.90) — how close a live comparison has to be to count as a match (Compare) or a
find (Find Template). Lower it if a node using this template is reporting `no_match`/
`not_found` when it visually looks right (motion blur, slight brightness differences, a small
animated element inside the captured region); raise it if it's reporting `match`/`found` too
eagerly against similar-but-wrong screens.

**Remove Template** deletes the selected template outright — any Compare or Find Template node
still pointing at it will show an "unknown template" warning (§8) until you either pick a
different template or delete the node.

A captured region is stored in the project's **reference resolution**, the same
resolution-independent convention every Action's touch coordinates use — so a template
captured while the mirror was one pixel size still lines up correctly if you reconnect later
and the mirror comes back at a different (downscaled) pixel size. The comparison itself is an
approximate one (nearest-neighbor-resized mean grayscale difference, not pixel-perfect OCR or
a real image-matching library) — it's meant for "does this region of the screen currently look
like X," not fine-grained visual diffing.

## 6. Wiring a graph: sequence, parallel, joins

- **Sequence**: connect node A's output to node B's input — B runs after A finishes.
- **A node with no incoming edges is a *root*** and starts immediately when you click Run.
  **More than one root starts all of them concurrently** — this is the practical way to author
  parallel branches today (see §12 for why "fork from a single node's output" doesn't work via
  the canvas the way the Repeat/Compare ports do).
- **A join**: if two or more different nodes each connect their output to the *same* target,
  that target waits until every one of those sources has finished before it starts. There's no
  cap on how many different sources can join into one target.
- **A node with no outgoing edges** just ends its branch — nothing else needs to be connected
  downstream of it.
- Every Repeat/Compare/Find Template named port (**body**/**after**, **match**/**no_match**,
  **found**/**not_found**) accepts at most one connection each via the canvas.

## 7. Running a graph and reading its log

Click **Run** (enabled once a run is loaded) to execute the graph against whatever's connected.
**Stop** requests it wind down — the node currently in flight (a Delay's sleep, or a single
action send, or one iteration of a Repeat) finishes, but nothing fires after that.

The **Game Run tab's own log panel** (below the warnings line, not the Mirror/Actions tab's
log) shows, as the run progresses:

```
Running 'right_jump_combo_x3'...
node n_right: ran action 'right'
node n_rep: repeat iteration 1/3
node n_jump: ran action 'jump'
node n_rep: repeat iteration 2/3
node n_jump: ran action 'jump'
node n_rep: repeat iteration 3/3
node n_jump: ran action 'jump'
node n_attack: ran action 'attack'
Run finished.
```

Other lines you may see, and what they mean:

- `node {id}: ran action {name!r} (N event(s) skipped)` — one or more of that action's events
  were dropped as no-ops (e.g. a RELEASE on a pointer that was never pressed) — same skip
  reporting as the Mirror/Actions tab's Test button.
- `node {id}: unknown action {name!r}, skipped` — the Action node's dropdown points at an
  action that no longer exists; nothing runs for that node, but the graph continues.
- `node {id}: repeat has no body connection, skipped` — a Repeat node with nothing wired to its
  **body** port does nothing and moves straight past.
- `node {id}: compare 'template_name' similarity=0.874 (threshold 0.90) -> no_match` — a
  Compare node's result, including the exact score, so you can tell how close it came.
- `node {id}: unknown template {name!r}, treated as no_match` / `node {id}: no live frame
  available yet, treated as no_match` — a Compare node that couldn't actually compare anything;
  it still deterministically follows the **no_match** edge rather than stalling the run.
- `node {id}: find_template 'template_name' best match (120, 340) similarity=0.912 (threshold
  0.90) -> found` — a Find Template node's result: the best-matching position (in reference
  coordinates), the score, and which edge it followed.
- `node {id}: unknown template {name!r}, treated as not_found` / `node {id}: no live frame
  available yet, treated as not_found` / `node {id}: find_template {name!r} region does not fit
  the live frame, treated as not_found` — a Find Template node that couldn't actually search
  anything; it still deterministically follows the **not_found** edge rather than stalling the
  run.
- `Run '{name}': no root node (every node has an incoming edge) -- nothing to run.` — every
  node in the graph has something pointing into it, so there's nowhere to start; break a cycle
  or free up a root.
- `Stop requested.` — you clicked Stop; the in-flight node still finishes its current step.

If you click **Run** with nothing connected, the message ("Run ignored: not connected.") also
appears in this same Game Run tab log. If you click Run with **no reference resolution set**,
though, the blocking explanation is logged to the **Mirror/Actions tab's** log panel instead
(the same check the Test button and canvas clicks use) — check there if Run silently does
nothing and the Game Run log shows no "ignored" line either.

## 8. Validation warnings reference

A red line (or several) below the canvas lists static problems with the current graph,
recomputed whenever you edit it or switch runs. None of these block **Run** — a graph can be
run with warnings showing — but a warned-about node typically won't do what you expect. Exact
messages:

| Warning | Meaning |
|---|---|
| `edge {id}: unknown source node {id!r}` / `unknown target node {id!r}` | An edge references a node id that doesn't exist (normally only reachable by hand-editing `project.yaml`). |
| `node {id}: unknown action {name!r}` | An Action node's dropdown points at an action that's been renamed or deleted. |
| `node {id}: repeat times must be >= 1` | A Repeat node's iteration count is invalid. |
| `node {id}: repeat has more than one body connection` | More than one edge is wired into the same Repeat node's **body** port (only reachable by hand-editing the file — the canvas caps this at one). |
| `node {id}: repeat has more than one after-loop connection` | Same, for **after**. |
| `node {id}: unknown template {name!r}` | A Compare or Find Template node's dropdown points at a template that's been renamed or deleted. |
| `node {id}: compare has more than one match connection` | More than one edge on the same Compare node's **match** port. |
| `node {id}: compare has more than one no_match connection` | Same, for **no_match**. |
| `node {id}: find_template has more than one found connection` | More than one edge on the same Find Template node's **found** port. |
| `node {id}: find_template has more than one not_found connection` | Same, for **not_found**. |
| `edge {id}: via={value!r} is only valid from a repeat, compare, or find_template node` | Somehow a `body`/`after`/`match`/`no_match`/`found`/`not_found`-tagged edge is coming out of a plain Action/Delay node — again, only reachable by hand-editing the file. |

## 9. The `project.yaml` file format for a run

A run is saved as part of the project file, alongside its actions and templates. Editing this
by hand is occasionally useful for things the canvas UI doesn't currently let you do (see §12)
— node ids are short hex strings (8 characters) but any unique string works fine if you're
writing them yourself.

```yaml
runs:
- name: right_jump_combo_x3
  nodes:
  - id: n_right
    kind: action
    x: 40          # canvas position only -- purely cosmetic, has no effect on execution
    y: 40
    action_name: right
  - id: n_rep
    kind: repeat
    x: 240
    y: 40
    times: 3
  - id: n_jump
    kind: action
    x: 440
    y: 0
    action_name: jump
  - id: n_attack
    kind: action
    x: 640
    y: 200
    action_name: attack
  edges:
  - id: e1
    source: n_right
    target: n_rep
  - id: e2
    source: n_rep
    target: n_jump
    via: body
  - id: e3
    source: n_rep
    target: n_attack
    via: after
```

A Compare node adds a `template_name` field instead of `action_name`/`frames`/`times`, and its
edges use `via: match` / `via: no_match`:

```yaml
  - id: n_check
    kind: compare
    x: 40
    y: 40
    template_name: game_over_banner
  ...
  edges:
  - id: e1
    source: n_check
    target: n_retry
    via: match
  - id: e2
    source: n_check
    target: n_keep_playing
    via: no_match
```

A Find Template node looks the same as Compare but with `kind: find_template`, and its edges
use `via: found` / `via: not_found`:

```yaml
  - id: n_locate
    kind: find_template
    x: 40
    y: 40
    template_name: coin
  ...
  edges:
  - id: e1
    source: n_locate
    target: n_grab
    via: found
  - id: e2
    source: n_locate
    target: n_wait
    via: not_found
```

`via` is omitted entirely for a plain edge (it defaults to `out`) — you'll only see it written
out for `body`/`after`/`match`/`no_match`/`found`/`not_found`.

Image Templates themselves are saved at the top level, alongside `actions`:

```yaml
templates:
- name: game_over_banner
  x: 900          # capture region, in the project's reference resolution
  y: 200
  width: 800
  height: 150
  threshold: 0.9
  image_w: 800    # the captured crop's own pixel size (may differ from width/height above
  image_h: 150    #   if it was captured at a different mirror pixel size than 1:1)
  pixels_b64: "..."   # base64-encoded raw grayscale bytes, image_w * image_h long
```

## 10. Worked examples

### A. Sequence + repeat + fan-in (see [`examples/mario_platformer.yaml`](examples/mario_platformer.yaml))

`right_jump_combo_x3`, shipped in that example project: press **right** once, then **jump**
three times in a row (the Repeat node's body), then **attack** once after the loop finishes
(the Repeat node's after edge). Open that project file to see it as a real, loadable run.

### B. A Compare-driven retry loop

A common shape once you have a "game over" template captured (§5): keep doing something until
the game-over banner shows, then tap Retry.

1. **+ Repeat Node**, times set high enough to cover a normal play session (e.g. `9999` — it
   only actually loops until you stop it, so an oversized count is harmless).
2. Wire **body** to an **Action** node running whatever the moment-to-moment gameplay action
   is (e.g. `jump`), and chain a **Compare** node after it using your `game_over_banner`
   template.
3. Wire the Compare node's **no_match** edge back to the same Action node that started the
   body (looping the check every iteration) — or simply leave the body as-is and rely on the
   Repeat's own iteration count, checking less often.
4. Wire the Compare node's **match** edge to an **Action** node running `tap_retry`, then click
   **Stop** once you see the retry action fire in the log (or, if you'd rather it stop itself,
   keep this branch outside the Repeat's body entirely and use the Repeat's **after** edge for
   whatever should happen once the loop count runs out).

## 11. Tips and troubleshooting

- **New nodes stack on top of each other** — drag them apart right after adding, before you
  lose track of which is which.
- **A Compare node reporting the "wrong" answer** — check the similarity score in the run log
  (§7) against the template's threshold; a score just under threshold usually means the
  captured region includes something that moves or changes slightly (an animated icon, a
  changing score digit) — recapture a tighter, more static region, or lower the threshold.
- **"unknown action"/"unknown template" warnings after a rename** — renaming an action or
  template doesn't currently update nodes that already reference the old name (there's no
  rename-in-place; add the action/template under its new name and re-pick it in every node
  that used the old one, or edit `project.yaml` directly for a bulk rename).
- **Run does nothing and no message appears in the Game Run tab** — check the Mirror/Actions
  tab's own log panel; a missing reference resolution logs there, not here (§7).
- **A Repeat or Compare node's second port looks unconnected on the canvas** — that's fine;
  **after** and **no_match** are both optional. An unconnected **body** on a Repeat is *not*
  fine (it's a documented no-op, §4) — check the warnings line if you're not sure a body
  connection landed.

## 12. Known limitations

- **You cannot fork a single Action/Delay node's output to more than one target via the
  canvas.** Every plain node's one **out** port accepts only one connection through
  drag-and-drop, even though the underlying engine (`run_engine.py`) and file format fully
  support a node with multiple outgoing edges firing them all concurrently — REPEAT's
  **body**/**after**, COMPARE's **match**/**no_match**, and FIND_TEMPLATE's
  **found**/**not_found** are separately-named ports and don't have this restriction between
  *each other*, but each of those named ports still caps at one connection too. In practice:
  author parallel branches as multiple independent **root** nodes (§6) instead, or hand-edit
  `project.yaml` (§9) to add extra edges sharing one `source` if you specifically need a
  mid-graph fan-out.
- **A node reused between a Repeat's body and the outer graph has undefined join behavior** —
  keep body nodes private to their Repeat (don't point some other, outer edge at a node that's
  already inside a Repeat's body), per `run_engine.py`'s own module docstring.
- **Renaming an action or template doesn't retarget existing nodes** — see §11.
- **Compare's and Find Template's image match are approximate**, not pixel-perfect or
  OCR-based — see §5.
- **A Find Template node's found (x, y) isn't wired into any downstream Action node by the
  canvas** — it's kept on the executor (`GameRunExecutor.last_found`, keyed by node id) for
  code driving a run programmatically to read back, but there's currently no UI for "tap
  wherever the last Find Template node found its match."
