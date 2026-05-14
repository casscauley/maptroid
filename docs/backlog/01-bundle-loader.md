# 01 — bundle loader management command

The maptroid-side half of asmr's `extractor/08`. asmr produces a bundle (records + PNG tree); this repo reads it and creates the world.

## What

A Django management command (`server/maptroid/management/commands/load_bundle.py`, or similar) that takes a path to an asmr bundle and:

1. Validates the bundle against the `data`-shape contract for each model (`World`, `Zone`, `Room`, `Item`). The asmr side targets `/api/schema/<model>/?schema=1`; this command is the enforcer at load time. Fail loud on schema drift — better to reject and update one side than silently ingest something subtly wrong.
2. Creates/updates rows in dependency order: `World` → `Zone` → `Room` → `Item`. Use natural keys for idempotency — most importantly `Room.key` (`<world_slug>_<hex>.png`, where `<hex>` is the room-header PC address in bank `$8F`). Re-running the loader on the same bundle should be a no-op (or a clean diff if asmr re-emitted with fixes).
3. Copies the PNG tree under `MEDIA_ROOT`: `sm_cache/<slug>/{layer-1,layer-2+layer-1,bts-extra}/<world_slug>_<hex>.png`. Mirror asmr's directory layout exactly — don't re-derive paths here.
4. Triggers `process_zone` (in `server/maptroid/sm.py`) per zone to build the DZI pyramids (`sm_zone/<slug>/<zone>/…`). Confirm whether asmr ships pyramids in the bundle or whether building them is always maptroid's job; the README implies the latter, but check before assuming.
5. Runs the existing `World.normalize()` / `Zone.normalize()` after rows are in place so offsets/bounds end up canonical.

## Bundle contract

This is the loader's API surface — keep it precise and write it down in this file as you build it. Source of truth for the *shape* is the models in `server/maptroid/models.py` (and the live `?schema=1` endpoints); asmr targets those. When the loader's contract document and asmr's `memory/maptroid-api.md` diverge, fix both in the same change set.

## Acceptance

- Load a freshly-built bundle for vanilla SM into a scratch world. Diff its API output against the real `world=1` — no field-level mismatches outside known sink-vs-game discrepancies that have already been recorded.
- Re-running the same bundle is idempotent.
- A bundle missing a required field, or with a shape asmr's `?schema=1` would reject, fails the command with a useful error — not a half-loaded world.

## Open questions for when you start

- Where does the bundle live on disk during a load? Probably a CLI arg pointing at asmr's output dir; the intake page (`03`) will wrap this with a temp dir per submission.
- Draft vs. published: should the loader always create the world `hidden=True` so staff can review before exposing? Likely yes for `03`'s flow; possibly optional for direct CLI use.
- Does anything in the existing `process_zone` path assume screenshot-derived inputs in a way that breaks for ROM-derived PNGs? Audit before assuming it just works.

## Non-goals

- A public ingestion API. Loader runs server-side, triggered by the management command (CLI) or the intake job (`03`).
- The pyramid generator itself — that's existing maptroid code (`sm.py` / `dzi.py`). The loader just calls into it.
- The asmr-side bundle emitter — that's asmr `extractor/08`.
