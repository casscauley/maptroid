"""
load_asmr_bundle — ingest an asmr extractor bundle into a maptroid world.

The asmr repo (~/projects/asmr) emits `bundle/<world>.json`: the ROM's
rooms reduced to maptroid's data shapes. This command is the "sink" that
loads such a bundle into the database. It is the maptroid-side half of
asmr's extractor track item 08 (world assembly + ingestion).

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
- Image pyramids. The bundle ships no per-room PNGs, so there is
  nothing to tile. Pyramid generation stays with maptroid's existing
  `scripts/2-process_sm.py` / `process_zone` path.

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
  ./manage.py load_asmr_bundle ../../asmr/bundle/vanilla.json
  ./manage.py load_asmr_bundle path/to/bundle.json --world-slug vanilla \\
      --world-name "Vanilla (asmr import)"
  ./manage.py load_asmr_bundle path/to/bundle.json --dry-run
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from maptroid.models import World, Zone, Room, Item


class Command(BaseCommand):
    help = 'Load an asmr extractor bundle (bundle/<world>.json) into a maptroid world.'

    def add_arguments(self, parser):
        parser.add_argument('bundle', type=Path, help='Path to the asmr bundle JSON.')
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
        path = opts['bundle']
        if not path.exists():
            raise CommandError(f'bundle not found: {path}')
        bundle = json.loads(path.read_text())

        slug = opts['world_slug'] or slugify(bundle['world'])
        name = opts['world_name'] or f'{bundle["world"]} (asmr import)'
        rooms = bundle.get('rooms') or []
        zones = bundle.get('zones') or []

        self.stdout.write(
            f'bundle: {path}  world={bundle.get("world")!r}  '
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
            for m in z['members']:
                ptr = m['pointer'].upper()
                member_zone_by_ptr[ptr] = zone
                member_xy_by_ptr[ptr] = list(m['zone_xy'])
            self.stdout.write(
                f'  zone: {"created" if zcreated else "reusing"} '
                f'{zslug!r}  {len(z["members"])} rooms  '
                f'world=[{wx},{wy},{ww},{wh}]')

        # Rooms. key = "<world-slug>_<POINTER>.png" — maptroid's convention.
        n_created = 0
        for rec in rooms:
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
            room.data = data
            room.save()  # recomputes geometry.screens / geometry.outer
        self.stdout.write(
            f'  rooms: {n_created} created, '
            f'{len(rooms) - n_created} updated')

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

        self._load_items(world, rooms)

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
