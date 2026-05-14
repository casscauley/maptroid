# maptroid backlog

Forward-looking work for this repo. The numbered `NN-name.md` files are a queue; each is one self-contained task and the numbering reflects **intended order, mostly by dependency**.

## Where this fits in the asmr ↔ maptroid arc

Most of the live work in this repo right now is the **ingestion side** of the pipeline being built in the sibling repo `~/projects/asmr/`. That repo's `docs/backlog/extractor/` is the source pipeline: ROM → bundle (records in maptroid's `data` shapes + the `sm_cache/<slug>/{layer-1,layer-2+layer-1,bts-extra}/` PNG tree). This repo loads that bundle, hosts the resulting world, and (eventually) puts a request-a-map page in front of the whole thing.

Read `~/projects/asmr/docs/backlog/extractor/README.md` and `~/projects/asmr/memory/goal-maptroid-export.md` before starting items here — they explain why the bundle shape is what it is and why "automatic first pass, curate in maptroid" is the bar.

**Direction of truth** (also stated in `CLAUDE.md`):
- *Record shapes* are this repo's call. If we change a `data` shape on a model, update `~/projects/asmr/memory/maptroid-api.md` in the same change set.
- *ROM-derived content* is asmr's call. When asmr's renderer and our `_maptroid-sink/` PNG disagree on a vanilla room, the cartridge is the tiebreaker — and the eventual fix is to replace the sink PNG, not patch around it (see item `04`).

## How to use this

Picking up a session:

1. Read the lowest-numbered file still in this directory.
2. Read the model/view/management-command files it references, plus the relevant asmr docs it points at.
3. Implement, exercise locally (both Django and Vue run on this machine — see `memory/local-dev-stack.md`), commit.
4. Move the file to `docs/backlog/done/` with a `**Status: DONE YYYY-MM-DD** in commit <sha>` header and any caveats — same convention asmr uses.

Don't reshuffle order without thinking — the loader has to exist before there's anything to refine; the intake page has to wait until the loader is stable enough that submitters won't hit obvious failures.

## Scope reminder

- **In:** anything maptroid has to do to consume asmr's bundle and present it as a world. Loader, post-import staff tooling, the public request page, replacing legacy sink renders with deterministic ROM-derived ones.
- **Out:** the extractor itself (lives in asmr — don't reimplement parsing/rendering here), the engine track (lives in asmr), Dread work (separate track, separate models).
- Romhacks are in scope — the whole point of the asmr pipeline is unblocking hacks that SMILE can't load.

## Items

- **`01` — bundle loader management command.** Read asmr's emitted bundle (`world.json`, `zones.json`, `rooms.json`, `items.json` + the `sm_cache/<slug>/…` PNG tree); create/update `World`/`Zone`/`Room`/`Item` rows; copy PNGs under `MEDIA_ROOT`; trigger zone tiling (`process_zone`). Stable bundle contract is the acceptance criterion. Pairs with asmr `extractor/08`.
- **`02` — post-import staff finishing tools.** The loader leaves known-manual steps (sub-zone refinement, elevator runs, transit links, `mc_data` polish). Audit which of those need new admin UI vs. work fine in the existing `/djadmin/` and Vue tools; build only what the gap demands.
- **`03` — request-a-map intake page.** Public page: paste a Metroid Construction link or upload a ROM → backend queues the asmr pipeline → result lands as a draft world for staff review. Don't start until `01` is solid. Coordinate the UX with the user. Pairs with asmr `extractor/09`.
- **`04` — replace legacy sink renders with ROM-derived ones.** Once asmr's renderer is golden on vanilla + the existing ~40 romhack worlds, swap the historical screenshot-pipeline PNGs in `_maptroid-sink/` (and the worlds already in production) with the deterministic ROM-derived renders. Maintenance task; depends on asmr's renderer being trusted and `01` being routine.

Items are sketches — flesh each out (model touchpoints, acceptance, edge cases) when it comes up. Propose new items for follow-up work you discover; let the user decide.
