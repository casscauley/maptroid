"""
load_asmr_bundle — ingest an asmr extractor bundle into a maptroid world.

The asmr repo (~/projects/asmr) is the ROM→pixels extractor. This command
is the "sink" that loads its output into the database — the maptroid-side
half of asmr's extractor track item 08 (world assembly + ingestion).

Two input shapes, same loader
-----------------------------
- **base ⊕ overrides (current).** asmr's pipeline-schema-overhaul splits a
  world into `bundle/<world>.base.json` (ROM-derived, no baked layout) and
  `<world>.overrides.json` (sparse operator edits). This command reads both,
  imports asmr's `tools/geo/bundle_schema`, and runs `normalize(merge(base,
  overrides))` — the one-time re-min / world-shift + geometry finalization
  that used to be baked into the bundle. Pass `--base <path>` (overrides is
  auto-found alongside it). Normalization (and the merge/geometry logic) lives
  in asmr and is guarded there by `verify_base_parity` — we import it rather
  than copy it so the two can't drift.
- **legacy single bundle.** The old `bundle/<world>.json` was already
  normalized. Pass it as the positional arg and it loads as before.

In both cases `_load` sees the identical normalized dict
(`{world, elevators, rooms:[...], zones:[...]}`), so everything below the
resolve step is shape-agnostic.

What it does
------------
- get_or_create a World (by slug) — re-running OVERWRITES, idempotent.
- get_or_create one Zone per bundle `zones[]` entry, writing world bounds
  straight from the bundle (the bundle is already normalized — extractor/25).
- get_or_create one Room per bundle room (by world + key), writing
  asmr-owned fields into Room.data: zone.bounds, holes, geometry.inner.

What it deliberately does NOT do
--------------------------------
- Doors. The bundle ships per-room `doors`, but maptroid's stored door
  `dir` convention is mirrored vs the bundle's and maptroid omits
  elevator-connection doors (see asmr extractor backlog item 20). Until
  that migration lands, writing doors would corrupt curated data — so
  this loader writes none. maptroid derives doors itself elsewhere.
- Elevators. The bundle's top-level `elevators` ({xys, variant} in the
  baked world frame) ARE loaded into World.data.elevators (links+elevators
  todo). Authored / ROM-seeded in the asmr arrangement world view.
- Links. Per-room `links` ({"x,y": {color, text}}) -> Room.data.links,
  loaded below; LinkOverlay pairs badges that share `text`.
- Enemies. PLM enemies/sprites still deferred (asmr extractor item 06).
  Items (the 100 vanilla pickups) ARE loaded — see _load_items.
- Image pyramids. This loader is records-only and ships no pixels. As of
  2026-06-13 (asmr extractor/66), zone compositing + DZI pyramid generation
  moved to asmr (`tools/geo/composite_zones.py` + `dzi.py`, `pyvips dzsave`):
  asmr writes the `sm_cache/` + `sm_zone/<…>.dzi` tree directly for
  asmr-sourced worlds. maptroid's `process_zone` is redundant for those worlds
  (it stays for legacy SMILE/Dread). Either way it's a separate render step,
  not this loader.

Normalization
-------------
Per asmr extractor/25, the bundle's `zones[]` is already canonically
normalized: every zone's `min(member.zone_xy) == (0, 0)`, every zone's
`world_wh` equals its content extent, and the leftmost-topmost zone sits
at `world_xy == (0, 0)`. So `Zone.normalize()` / `World.normalize()`
would be structural no-ops here — we skip them entirely.

Safety
------
Defaults to world-slug `vanilla` (the bundle's own `world` field), i.e.
a SCRATCH world — it does NOT touch the curated `super-metroid` world.
Point `--world-slug super-metroid` at the real world only deliberately,
and not before backlog item 20 is resolved.

Usage
-----
  # base ⊕ overrides (current): overrides auto-found next to base
  ./manage.py load_asmr_bundle --base ../../asmr/bundle/vanilla.base.json
  ./manage.py load_asmr_bundle --base ../../asmr/bundle/scm.base.json \\
      --overrides ../../asmr/bundle/scm.overrides.json --dry-run
  # legacy single normalized bundle
  ./manage.py load_asmr_bundle ../../asmr/bundle/vanilla.json
  ./manage.py load_asmr_bundle path/to/bundle.json --world-slug vanilla --dry-run
"""
import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from maptroid.models import World, Zone, Room, Item


def _resolve_base_overrides(base_path, overrides_path, asmr_geo):
    """Read base ⊕ overrides and return the normalized legacy-shape bundle.

    Imports asmr's `bundle_schema` (single source of truth for merge +
    normalize + geometry finalization, guarded by `verify_base_parity` in
    asmr) rather than reimplementing it here. `asmr_geo` overrides where that
    module is found; default is `<asmr-repo>/tools/geo` derived from the base
    file's location (`<asmr>/bundle/<world>.base.json`)."""
    base_path = base_path.resolve()
    geo = (asmr_geo or base_path.parent.parent / 'tools' / 'geo').resolve()
    if not (geo / 'bundle_schema.py').exists():
        raise CommandError(
            f'asmr bundle_schema not found under {geo} — pass --asmr-geo '
            'pointing at the asmr repo\'s tools/geo directory.')
    if str(geo) not in sys.path:
        sys.path.insert(0, str(geo))
    try:
        import bundle_schema  # noqa: E402  (asmr module, path-injected above)
    except ImportError as exc:
        raise CommandError(f'could not import asmr bundle_schema from {geo}: {exc}')

    base = json.loads(base_path.read_text())
    if overrides_path is None:
        sib = base_path.with_name(base_path.name.replace('.base.json', '.overrides.json'))
        overrides = json.loads(sib.read_text()) if sib.exists() else {}
    else:
        overrides = json.loads(overrides_path.read_text())

    bundle = bundle_schema.normalize(bundle_schema.merge(base, overrides))
    # normalize() drops provenance; carry it for the load banner. As of asmr
    # extractor/68 provenance lives in a sibling `<world>.meta.json` (base.json
    # is content-only); read it there, falling back to any inline value on a
    # pre-split base.json so older bundles still banner correctly.
    meta_sib = base_path.with_name(base_path.name.replace('.base.json', '.meta.json'))
    meta = json.loads(meta_sib.read_text()) if meta_sib.exists() else {}
    for k in ('extractor_version', 'rom_sha256', 'generated', 'name'):
        v = meta.get(k) if meta.get(k) is not None else base.get(k)
        if v is not None:
            bundle.setdefault(k, v)
    return bundle


class Command(BaseCommand):
    help = 'Load an asmr extractor bundle (bundle/<world>.json) into a maptroid world.'

    def add_arguments(self, parser):
        parser.add_argument(
            'bundle', type=Path, nargs='?', default=None,
            help='Path to a legacy normalized bundle JSON (omit when using --base).')
        parser.add_argument(
            '--base', type=Path, default=None,
            help='Path to <world>.base.json (current base ⊕ overrides input).')
        parser.add_argument(
            '--overrides', type=Path, default=None,
            help='Path to <world>.overrides.json (default: sibling of --base).')
        parser.add_argument(
            '--asmr-geo', type=Path, default=None,
            help="asmr repo's tools/geo dir (default: derived from --base path).")
        parser.add_argument(
            '--world-slug', default=None,
            help="World slug to load into (default: the bundle's `world` field).")
        parser.add_argument(
            '--world-name', default=None,
            help='World display name when creating it (default: derived from slug).')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Run inside a transaction and roll back — report only.')

    def handle(self, *args, **opts):
        base, legacy = opts['base'], opts['bundle']
        if bool(base) == bool(legacy):
            raise CommandError('pass exactly one of: positional <bundle> (legacy) '
                               'or --base <world>.base.json (base ⊕ overrides).')
        if base is not None:
            if not base.exists():
                raise CommandError(f'base not found: {base}')
            if opts['overrides'] is not None and not opts['overrides'].exists():
                raise CommandError(f'overrides not found: {opts["overrides"]}')
            bundle = _resolve_base_overrides(base, opts['overrides'], opts['asmr_geo'])
            src = base
        else:
            if not legacy.exists():
                raise CommandError(f'bundle not found: {legacy}')
            bundle = json.loads(legacy.read_text())
            src = legacy

        slug = opts['world_slug'] or slugify(bundle['world'])
        name = opts['world_name'] or f'{bundle["world"]} (asmr import)'
        rooms = bundle.get('rooms') or []
        zones = bundle.get('zones') or []

        self.stdout.write(
            f'bundle: {src}  world={bundle.get("world")!r}  '
            f'rooms={len(rooms)}  zones={len(zones)}  '
            f'extractor={bundle.get("extractor_version")}')
        if slug == 'super-metroid':
            self.stdout.write(self.style.WARNING(
                '  !! targeting the curated super-metroid world — '
                'this overwrites hand-built data.'))

        try:
            with transaction.atomic():
                self._load(bundle, slug, name, rooms, zones)
                if opts['dry_run']:
                    self.stdout.write(self.style.WARNING('dry-run — rolling back.'))
                    transaction.set_rollback(True)
        except Exception as exc:  # surface, don't half-commit
            raise CommandError(f'load failed: {exc}')

        if not opts['dry_run']:
            self.stdout.write(self.style.SUCCESS('done.'))

    def _load(self, bundle, slug, name, rooms, zones):
        world, created = World.objects.get_or_create(
            slug=slug, defaults={'name': name})
        # asmr-loaded worlds are full vanilla replicas — surface them in the
        # world listing the same way the curated super-metroid world is.
        if world.data.get('hidden'):
            world.data['hidden'] = False
            world.save()
        self.stdout.write(
            f'world: {"created" if created else "reusing"} '
            f'{world.name!r} (id={world.id}, slug={world.slug})')

        rooms_by_ptr = {r['pointer'].upper(): r for r in rooms}

        # Hidden rooms (extractor/29) are dropped from the world map at ingest:
        # excluded from zone membership, never created, and any existing copy
        # is deleted below (which lets its zone fall to the empty-zone prune).
        # The bundle still carries them as zone members so the arrangement UI's
        # hidden view can list them — maptroid simply never renders them.
        visible_rooms = [r for r in rooms if not r.get('hidden')]
        hidden_ptrs = {r['pointer'].upper() for r in rooms if r.get('hidden')}

        # One Zone per bundle zones[] entry. Bundle is pre-normalized
        # (extractor/25) — world bounds and member zone_xy are authoritative.
        zone_by_slug = {}
        member_zone_by_ptr = {}
        member_xy_by_ptr = {}
        for z in zones:
            zslug = z['slug']
            zname = z.get('name') or (z['slug'].replace('-', ' ').title()
                     if '__' not in z['slug'] else z['slug'])
            zone, zcreated = Zone.objects.get_or_create(
                world=world, slug=zslug, defaults={'name': zname})
            if z.get('name'):                 # rename override (extractor/29)
                zone.name = z['name']
            wx, wy = z['world_xy']
            ww, wh = z['world_wh']
            zone.data['world'] = {'bounds': [wx, wy, ww, wh]}
            # metadata overrides (extractor/29), loader-authoritative.
            zone.data['hidden'] = bool(z.get('hidden'))
            if z.get('color'):
                zone.data['color'] = z['color']
            else:
                zone.data.pop('color', None)
            zone.save()
            zone_by_slug[zslug] = zone
            n_members = 0
            for m in z['members']:
                ptr = m['pointer'].upper()
                if ptr in hidden_ptrs:        # hidden room — not a map member
                    continue
                member_zone_by_ptr[ptr] = zone
                member_xy_by_ptr[ptr] = list(m['zone_xy'])
                n_members += 1
            self.stdout.write(
                f'  zone: {"created" if zcreated else "reusing"} '
                f'{zslug!r}  {n_members} rooms  '
                f'world=[{wx},{wy},{ww},{wh}]')

        # Rooms. key = "<world-slug>_<POINTER>.png" — maptroid's convention.
        n_created = 0
        for rec in visible_rooms:
            ptr = rec['pointer'].upper()
            key = f'{slug}_{ptr}.png'
            zone = member_zone_by_ptr.get(ptr)
            if zone is None:
                # Defensive: every bundle room should appear in exactly one
                # zone (compose_zones guarantees this). Skip orphans loudly.
                self.stdout.write(self.style.WARNING(
                    f'  room {ptr} not in any bundle.zones[].members — skipping'))
                continue
            try:
                room = Room.objects.get(world=world, key=key)
            except Room.DoesNotExist:
                room = Room(world=world, key=key)
                n_created += 1
            room.zone = zone
            # name: rename override (extractor/29) wins, else keep a curated
            # name, else fall back to the area label.
            room.name = rec.get('name') or room.name or rec.get('area')
            data = room.data or {}
            # asmr-owned fields only — merge, preserving any maptroid-side keys.
            zx, zy = member_xy_by_ptr[ptr]
            data.setdefault('zone', {})
            data['zone']['bounds'] = [zx, zy, rec['width'], rec['height']]
            data['holes'] = rec.get('holes') or []
            data['hidden'] = bool(rec.get('hidden'))   # extractor/29, loader-authoritative
            # render flags (extractor/27), loader-authoritative. Defaults:
            # invert_layers off, clear_holes on. asmr worlds don't set a
            # world/zone clear_holes, so this per-room value governs in
            # process_zone's `world or zone or room` hierarchy.
            data['invert_layers'] = bool(rec.get('invert_layers'))
            data['clear_holes'] = rec.get('clear_holes', True)
            data.setdefault('geometry', {})
            data['geometry']['inner'] = rec.get('geometries') or []
            # exterior boundary override (extractor/27): the bundle's
            # `geometry_override` is the room outline ring. maptroid's
            # get_room_walls builds geometry.outer (the zone-coloured line)
            # from it; absent = derive the outer from the room footprint.
            if rec.get('geometry_override'):
                data['geometry_override'] = rec['geometry_override']
            else:
                data.pop('geometry_override', None)
            # link badges (links+elevators todo), loader-authoritative:
            # {"x,y": {color, text}} -> Room.data.links. LinkOverlay pairs
            # badges that share `text`.
            data['links'] = rec.get('links') or {}
            # CRE block overlay (asmr extractor/30): breakable/shot/bomb blocks,
            # spikes, conveyors, door-frame glyphs -> the "walls" view's stamped
            # icons (make_walls_image). Deterministic, loader-authoritative.
            data['cre'] = rec.get('cre') or {}
            data['cre_overrides'] = rec.get('cre_overrides') or []
            data['cre_hex'] = rec.get('cre_hex') or {}
            room.data = data
            room.save()  # recomputes geometry.screens / geometry.outer
        self.stdout.write(
            f'  rooms: {n_created} created, '
            f'{len(visible_rooms) - n_created} updated')

        # Delete rooms the visible bundle no longer declares — rooms removed
        # from the crawl AND (extractor/29) rooms now hidden. Items cascade.
        # This empties any zone that held only hidden/removed rooms, so the
        # prune below can drop it (e.g. a retired ztrash zone's rooms have all
        # moved back to their area zones, leaving it empty).
        visible_keys = {f'{slug}_{r["pointer"].upper()}.png' for r in visible_rooms}
        orphans = Room.objects.filter(world=world).exclude(key__in=visible_keys)
        n_orphan = orphans.count()
        if n_orphan:
            orphans.delete()
            self.stdout.write(f'  rooms: deleted {n_orphan} hidden/removed')

        # Prune zones the bundle no longer declares (extractor/24: a subzone
        # deleted in the arrangement UI drops out of `subzones[]`, so
        # compose_zones stops emitting it). Only empty zones are removed — a
        # base area always has rooms and is always present, so it's safe.
        bundle_slugs = {z['slug'] for z in zones}
        stale = (Zone.objects.filter(world=world)
                 .exclude(slug__in=bundle_slugs)
                 .filter(room__isnull=True))
        if stale.exists():
            removed = sorted(stale.values_list('slug', flat=True))
            stale.delete()
            self.stdout.write(f'  zones: pruned {len(removed)} empty/removed: {removed}')

        # World-level elevators (links+elevators todo): {xys, variant} in the
        # baked world frame -> World.data.elevators. ElevatorOverlay draws
        # variant 'line' shafts. The bundle is pre-normalized (extractor/25),
        # so World.normalize() won't re-shift the xys.
        world.data['elevators'] = bundle.get('elevators') or []
        world.save()
        self.stdout.write(f'  elevators: {len(world.data["elevators"])}')

        self._load_items(world, visible_rooms)

    def _load_items(self, world, rooms):
        """Wipe-and-rewrite items for this world. The frontend's MapView
        bails (ready === false) when world_items.length is 0, so without
        this the viewer would never mount for an asmr-loaded world.

        `type`/`room_xy`/`plm_id`/`arg` are asmr-owned (from the bundle).
        `modifier` (the chozo/in-block variant the ROM doesn't reliably
        encode — see asmr's extract_plms docstring) is maptroid-side
        curation, so we **preserve** any curated value across the
        re-ingest instead of nulling it."""
        # Snapshot curated modifiers before the wipe, keyed by (room, pos).
        prior_modifier = {
            (it.room_id, tuple(it.data.get('room_xy') or ())): it.data['modifier']
            for it in Item.objects.filter(room__world=world)
            if it.data.get('modifier')
        }
        Item.objects.filter(room__world=world).delete()
        rooms_by_ptr = {r.key.removeprefix(world.slug + '_').removesuffix('.png'): r
                        for r in Room.objects.filter(world=world)}
        n = 0
        for rec in rooms:
            ptr = rec['pointer'].upper()
            room = rooms_by_ptr.get(ptr)
            if room is None:
                continue
            for it in rec.get('items', []):
                xy = it['room_xy']
                data = {'type': it['type'], 'room_xy': xy}
                # asmr forensic fields — maptroid has no schema for them, but
                # carrying them keeps the bundle's data from being dropped.
                for k in ('plm_id', 'arg'):
                    if k in it:
                        data[k] = it[k]
                # modifier: prefer a preserved curated value, then any the
                # bundle supplies (currently none — deferred to curation).
                modifier = prior_modifier.get((room.id, tuple(xy))) or it.get('modifier')
                if modifier:
                    data['modifier'] = modifier
                Item.objects.create(room=room, zone=room.zone, data=data)
                n += 1
        self.stdout.write(f'  items: {n} loaded')
