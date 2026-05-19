# Project conventions for maptroid

maptroid is the Django+Vue webapp at `maptroid.unrest.io` that hosts Super Metroid (and hack) world maps — `world` / `zone` / `room` / `item` records plus rendered map-tile PNGs. Global conventions live in `~/.claude/CLAUDE.md`. **Read that first; this file only adds repo-specifics.**

## Stack

- **`server/`** — Django 4.0 + DRF-style views, Postgres. Python venv conventions per `~/.claude/CLAUDE.md` ("Django project conventions"): functional views, `.venv/bin/python ./server/manage.py …` for management commands and migrations.
- **`client/`** — Vue 3 + Vue CLI (not Vite), Tailwind, the `@unrest/*` shared libs (see `package.json`). UI conventions per `~/.claude/CLAUDE.md` (".html + .vue conventions", "CSS conventions") apply — self-closing empty tags, `const fn = () =>`, `defineModel()`, ABEM-via-`@apply`, etc.
- **Image processing** lives in the `maptroid` Django app: `sm.py` (`process_zone`, the layer compositing pipeline), `dzi.py` (DeepZoom pyramids), `plm.py`, `cre.py`, `smile.py`. OpenCV (`cv2`) + scikit-image + shapely.

## Asset tree

- `MEDIA_ROOT = server/../.media` → `~/projects/maptroid/.media/`
- Per-world cache: `.media/sm_cache/<world_slug>/{layer-1,layer-2+layer-1,bts-extra}/<world_slug>_<header_hex>.png`
- DeepZoom pyramids: `.media/sm_zone/<world_slug>/<zone>/...dzi`
- `SINK_DIR = .media/_maptroid-sink/` — historical screenshot-based renders, used as the validation oracle by the sibling `~/projects/asmr` repo (it mirrors this dir locally).

## The asmr ↔ maptroid contract

The sibling repo at **`~/projects/asmr`** is the ROM→pixels extractor pipeline. It reads ROMs and produces the bundle maptroid ingests: records (`world.json` / `zones.json` / `rooms.json` / `items.json` in the exact `data` shapes maptroid expects) plus the PNG tree above. Two contract documents in asmr are canonical:

- `~/projects/asmr/docs/maptroid-ingestion/` — bundle format, layer-compositing reverse-engineering of `process_zone`, anything maptroid needs to know about the upstream pipeline.
- `~/projects/asmr/memory/maptroid-api.md` — read-API record shapes (`/api/schema/<model>/?world=1`) the extractor targets for field-level parity.

**Direction of truth:** the *record shapes* are maptroid's call (this repo wins disputes about schema). The *ROM-derived content* is asmr's call (that repo wins disputes about what tiles/items/geometry a room has). When the two disagree about a vanilla render, the actual game on accurate hardware/emulator is the tiebreaker — see asmr's "escape hatch" notes.

## Cross-repo work

- Loader code that consumes asmr's bundle (the planned `extractor/08` capstone in asmr) lives **here**, as a Django management command — not in asmr. asmr emits the bundle; this repo reads it.
- When changing a `data` shape on a model, update `~/projects/asmr/memory/maptroid-api.md` in the asmr repo as part of the same change set so the extractor sees it. Don't silently diverge.
- Migrations: always `.venv/bin/python ./server/manage.py makemigrations` (per global conventions), never hand-write migration files.

## Local dev notes

- `server/install.sh` and `client/install.sh` are the bootstrap scripts.
- `process-zone` (in `sm.py`) is the rendering pipeline that produces the PNG tree from SMILE exports. Reverse-engineered in detail in `~/projects/asmr/docs/maptroid-ingestion/layer-compositing.md` — read that before touching the compositing path.
