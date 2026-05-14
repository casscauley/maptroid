# 02 — post-import staff finishing tools

The loader (`01`) produces a *first pass* world. Several refinements are explicitly manual per the asmr contract:

- **Sub-zone refinement.** asmr emits one zone per SM area (8 total for vanilla). maptroid zones are finer than that — splits are a human/editor call. There's no automatic source of truth for them.
- **Elevator runs.** `World.data.elevators` `[{xys:[[x,y]…], variant}]` is hand-curated; the ROM doesn't encode the cosmetic run.
- **Transit links.** `Item.data.type` includes `transit__*` records that pair across rooms; pairing is human-judged.
- **`World.data.mc_data`** — author/title/rating/runtime/difficulty/genre — comes from the submitter, not the ROM.

## What

Audit before building. The question for each manual step is *does the existing tooling already handle this well enough, or is the gap painful?*

- Try doing every step end-to-end on a freshly-loaded scratch world using only the existing `/djadmin/maptroid/{world,zone,room,item}/` admin + the Vue editor surfaces already present. Time it. Note where you reach for something that doesn't exist or hits a sharp edge (e.g. splitting a zone may require manually re-bounding every affected room).
- Only after that audit, decide what to build. Likely candidates, in rough priority order:
  - A zone-split tool in the Vue editor (draw a new zone boundary inside an existing zone; rooms whose `zone.bounds` fall inside the new boundary move; `Zone.normalize()` re-runs on both sides).
  - An elevator-run editor (click rooms to add to an `xys` list; pick a `variant`).
  - A transit-pair picker (select two `transit__*` items; record the pairing).
  - An `mc_data` form on `World` (likely fine in admin — verify).

## Acceptance

Per tool you build: a staff member can complete that finishing step on a fresh import without dropping to the Django shell or hand-editing JSON in admin.

## Open questions for when you start

- The Vue editor's current surface — what already exists for room/zone manipulation? Decide reuse vs. new screens.
- Does any of this overlap with what would have been built for the deferred "editor track" in asmr? If so, scope ruthlessly — this item only needs to cover the post-import finishing steps, not a general-purpose editor.

## Non-goals

- A general-purpose room/zone/item editor — this exists to close the loader's known-manual gaps, nothing more.
- Anything the existing admin already handles acceptably. Audit first.
- Automating the steps themselves — the asmr contract says these are human calls, period.
