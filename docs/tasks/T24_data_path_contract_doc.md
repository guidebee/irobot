# T24 — Write the data-path contract and correct the docs

Status: open

| | |
|---|---|
| Fixes | [DP17](../gym_data_path_review.md#low-severity); final doc pass for DP02 and DP12 |
| Priority / size | P1 / S |
| Depends on | T07, T08, T09, T10, T11, T12, T14, T18, T19, T20 (write it last in its lane; it describes what they built) |
| Area | Docs |
| Needs a device | No |

## Why

Today, what an agent can rely on from irobot is scattered across code comments, three design docs
and `tools/README.md`, and some of it is wrong. For example, "real, undownscaled device resolution"
really means the video stream's resolution, which differs from the device's when `--max-size` or
`--crop` is used (DP17). Whoever builds the Gym env needs one page that says what's guaranteed.

## Steps

1. **Create `docs/agent_data_path.md`** with one short section per topic. For each, state the
   guarantee, the limits, and the code that implements it (file names, not line numbers, since
   those drift):
   - **Frames:** rate and throttle (trailing edge, `--agent-max-fps`, T10); what's sent (grey ≤800 px,
     colour ≤240 px with phash; area-filtered, T06); what happens on a static screen (encoder repeat
     about every 100 ms, depending on the device's encoder).
   - **Frame identity and time:** header `id`, the metadata buffer layout, how to compute a frame's
     age (T08, T21).
   - **Resolution:** it's the *video stream's* size, and it's what touch `screen_size` must equal;
     announced before the first frame of a new size (T07); with `--max-size`, touch precision is one
     video pixel.
   - **Backpressure:** newest frames win, and resolution messages are never dropped (T09).
   - **Actions:** tap hold time (T12), where releases land (T11), pointer ids, and what happens to
     held fingers when the display changes (T14).
   - **Feedback:** how to subscribe to input statistics and what each counter means (T16–T18).
   - **Recording:** what's recorded, by whom, with frame numbers (T19).
   - **Several clients:** the warning and `--agent-exclusive-control` (T20).
   - **Security:** loopback-only ports, no authentication, so any local process can drive the
     device.
2. **Fix wording elsewhere** so nothing contradicts that page:
   - "real, undownscaled device resolution" (or similar) → "video stream resolution" in
     `src/message/blob_msg.hpp`, `src/agent/agent_manager.*`, `tools/agent_client.py`,
     `tools/README.md`, and the main `README.md`;
   - `tools/README.md`'s protocol reference: make sure it describes the length-prefixed control
     framing (the Jev plan's WP0.2 may already have fixed this; check), the metadata buffer, and the
     subscribe message;
   - the main `README.md`'s recording claim, now that T19 made it true: add a pointer to the new page.
3. **Link the new page** from the main `README.md` ("The AI Agent API" section), `tools/README.md`,
   and `docs/gym_jev_implementation_plan.md` §2.
4. **Update the review.** In `docs/gym_data_path_review.md`, mark each finding fixed by a merged task
   (add a "Status" column to the summary table with the PR number), and leave anything still open
   clearly marked.

## Done when

- `docs/agent_data_path.md` exists and every statement in it matches the code on `master`. A
  reviewer should be able to spot-check any three statements against the code in a few minutes.
- `grep -rni "undownscaled" .` finds nothing that describes the resolution message wrongly.
- The review's summary table shows the status of every finding.
