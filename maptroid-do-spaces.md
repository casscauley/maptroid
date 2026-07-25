# maptroid media on DO Spaces — spec

Status: **spec only, nothing implemented.** Written 2026-07-25.

Companion to `txrx.org/txrx-do-spaces.md`, which is the working reference. Same
bucket (`skade`, nyc3), same pattern, new prefix `maptroid/`.

## Headline: the txrx pattern only covers ~5% of this

txrx's media was 3.3G of `FileField` uploads, so swapping `STORAGES` moved
essentially all of it. maptroid is not like that. **23G of its 30G never touches
Django's storage API** — it is written with raw filesystem calls:

```python
# server/maptroid/sm.py:61-66
CACHE_DIR = mkdir(settings.MEDIA_ROOT, f'sm_cache/{world.slug}')
LAYER_DIR = mkdir(settings.MEDIA_ROOT, f'sm_zone/{world.slug}/layer-1')
```

A storage backend intercepts `FileField.save()` and `default_storage`. It does
nothing for `os.path.join` + `PIL.Image.save()`. Change `STORAGES` alone and
those writers keep writing to local disk, except now nginx no longer serves that
path — so the render pipeline appears to work and the images 404.

## The 30G, by how it is actually written

| Path | Size | Written by | Disposition |
| --- | --- | --- | --- |
| `sm_zone/` | 12G | `sm.py` — raw fs | **Track 3** — needs code changes |
| `sm_cache/` | 11G | `sm.py`, `plm.py` — raw fs | **Track 2** — it is a cache; delete |
| `trash/` | 4.2G | scratch | **Track 2** — delete |
| `_maptroid-sink/` | 2.5G | **symlink to a git repo** | **Do not touch** — see below |
| `temp/` | 1.6G | scratch | **Track 2** — delete |
| `screenshots/` | 1.2G | `ImageField(upload_to="screenshots")` | **Track 1** — Spaces |
| `dread_zones/` | 511M | unverified | **Unknown** — resolve before acting |
| `labbooks/` | 445M | `labbook.py` — raw fs | Track 3 (small) |
| `deepzoom/` | 76M | `deepzoom.py` — raw fs `tile.save()` | Track 3 (small) |
| `hashed_sprites/` | 27M | `ImageField` | **Track 1** — Spaces |
| `uploads/` | 9.8M | source ROMs/data | **Track 1** — Spaces (and back it up) |

`FileField`/`ImageField` declarations, i.e. everything Track 1 covers:
`hashed_sprites`, `smile_characters`, `smile_sprites`, `screenshots`, `output`,
`channel_icons`, `video_thumbnails`, `skill_resources` — **~1.3G total.**

## Do not migrate `_maptroid-sink`

`server/.media/_maptroid-sink` is a **symlink** to `~/projects/_maptroid-sink`, a
separate git repository (121 commits, level with its GitHub remote — already
backed up). It is referenced by `SINK_DIR` in settings, by dedicated
`location /media/_maptroid-sink/` blocks in nginx, and fetched directly by six
Vue components. Pushing it to Spaces would duplicate version-controlled content
and break all three. Leave it exactly as it is.

## Three tracks, in order of value-per-risk

### Track 2 first — delete, don't migrate (≈17G, no code)

The largest win needs no Django changes at all. `sm_cache` is a cache, and
`trash`/`temp` are scratch by name. txrx's playbook set the precedent: it
explicitly did **not** ship `.media/cache/` (216M of sorl thumbnails) because it
"regenerated on demand".

Blocking question: **is `sm_cache` genuinely regenerable, and how long does a
rebuild take?** If regenerating 11G takes hours of CPU on a 3.8 GiB box, "it is a
cache" is technically true and operationally useless. Verify against one world
slug before deleting the lot.

### Track 1 — the txrx pattern, verbatim (≈1.3G, low risk)

Proven, and mostly copy-paste from `txrx.org/main/settings/spaces.py`:

1. `requirements.txt`: add `django-storages[boto3]` and `boto3` (maptroid has
   neither; txrx has both).
2. New `server/main/settings/spaces.py` mirroring txrx's, with
   `"location": "maptroid"` so keys become `maptroid/<upload_to>/<file>`, and
   `MEDIA_URL = "https://skade.nyc3.cdn.digitaloceanspaces.com/maptroid/"`.
   Keep txrx's guard — fall back to local storage when the key is absent, so a
   fresh dev machine still works.
3. Credentials in `local.py`, not committed.
4. Sync the FileField directories up with the s3cmd already installed:
   ```bash
   ~/.local/bin/s3cmd sync -P server/.media/screenshots/ s3://skade/maptroid/screenshots/
   ```
   …and the same for the seven other `upload_to` directories.
5. Leave the nginx `/media/` alias in place — anything not yet migrated keeps
   being served locally.

**Caveat:** existing `ImageField` rows store paths relative to storage, so once
`STORAGES` flips, old rows resolve against Spaces. The sync must complete
*before* the switch or every existing image 404s.

### Track 3 — the 12G of `sm_zone` (real work)

Two viable shapes:

**3a. Route the writers through `default_storage`.** Replace the `mkdir` +
`PIL.save(path)` pattern in `sm.py`, `plm.py`, `labbook.py` and `deepzoom.py`
with `default_storage.save()`. Correct, but it is a real refactor of the render
pipeline, and anything that later *reads back* from those paths has to change
too — worth grepping for read-side `os.path` use before committing to this.

**3b. Generate locally, sync up, serve from the CDN.** Leave the pipeline writing
to local disk, add an `s3cmd sync` at the end of a render run, and point only the
*serving* URL at Spaces. Much smaller change; the cost is that local disk still
needs headroom for a working set during generation.

3b is the pragmatic choice if renders are infrequent and batch-shaped. 3a is
right if images are produced on demand during requests. **Decide by checking
whether `sm.py` is invoked from a view or from a script/management command.**

## Prerequisites

- Confirm CDN is enabled on the `skade` bucket (DO console → bucket → Settings).
- **Rotate the Spaces key first.** `txrx-do-spaces.md` records that the current
  key/secret "was pasted in chat while setting this up" and should be rotated at
  https://cloud.digitalocean.com/account/api/spaces. Doing that before adding a
  second consumer means updating one `local.py`, not two.
- Bucket currently holds `txrx/`. Adding `maptroid/` under the same bucket
  matches the "one key prefix per project" convention already established.

## Open questions

1. Is `sm_cache` regenerable, and at what cost? (gates Track 2, the biggest win)
2. What is `dread_zones/` (511M) and what writes it?
3. Is `sm.py` called from a request path or only from scripts? (picks 3a vs 3b)
4. Does anything read back from `MEDIA_ROOT` by filesystem path after writing?
   Those readers break under 3a and need finding first.

## What "done" looks like

- `du -sh server/.media` well under 5G, down from 30G
- maptroid.unrest.io renders zones and screenshots identically, served from
  `skade.nyc3.cdn.digitaloceanspaces.com`
- a fresh checkout with no Spaces key still runs on local storage
- `_maptroid-sink` untouched and still served locally
