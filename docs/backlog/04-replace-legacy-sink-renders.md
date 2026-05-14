# 04 — replace legacy sink renders with ROM-derived ones

Maintenance, not new capability. Last item in the queue because it depends on (a) asmr's renderer being trusted as a source of truth, and (b) the loader (`01`) being routine enough to re-ingest existing worlds without drama.

## Why

The current PNG tree under `.media/sm_cache/` (and the mirror in `_maptroid-sink/`, which asmr uses as its validation oracle) was produced by the old pipeline: SMILE + `pyautogui` screenshotting per room, stitched. That pipeline has its own artefacts — wrong colours under certain palettes, layer-2/CRE glitches, the kinds of things that show up when asmr's ROM-direct renderer disagrees with the sink and the cartridge sides with asmr (see asmr's "escape hatch" — the agentic loop where the user adjudicates sink-vs-game disputes).

asmr's `memory/goal-maptroid-export.md` is explicit: *"plan to replace that sink PNG with ours later."* This item is "later."

## What

Once asmr's renderer is golden on vanilla and on the ~40 existing romhack worlds:

1. For each existing world, run the asmr pipeline to produce a fresh PNG tree.
2. Use `01`'s loader (in re-ingest mode) to overwrite the sink PNGs in place. Records should also re-import cleanly if asmr's record passes are golden — but treat *records* with more care than tiles, since staff may have made manual edits since the original import (sub-zone splits, elevator runs, transit links, `mc_data`). Don't clobber that work. Either skip record updates by default and let staff opt-in per world, or diff first and surface anything that would change.
3. Rebuild the DZI pyramids.
4. Update `_maptroid-sink/` (asmr's mirror) by re-pulling — that mirror is downstream of `.media/sm_cache/`, not upstream.

## Acceptance

- A world that was visibly broken by a sink artefact (collect a list as the agentic loop in asmr surfaces them) now renders correctly with the asmr-derived PNGs.
- No staff-curated record fields (`elevators`, `transit__*` pairings, sub-zone splits, `mc_data`) are lost in the swap.

## Open questions for when you start

- Roll out world-by-world (low risk, slow) or in a batch (faster, needs trust in `01`'s re-ingest path). Probably world-by-world for the first few, then batch.
- Whether to keep the pre-swap PNGs around as a rollback — disk-cheap insurance.

## Non-goals

- Re-running the asmr pipeline as a regular thing — this is a one-time swap per world. After it, asmr's renderer is just what `01` consumes.
- Touching records for worlds where staff have heavily curated post-import. Per-world decision.
