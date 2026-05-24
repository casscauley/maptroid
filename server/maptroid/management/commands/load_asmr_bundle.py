"""
load_asmr_bundle — ingest an asmr extractor bundle into a maptroid world.

The asmr repo (~/projects/asmr) emits `bundle/<world>.json`: the ROM's
rooms reduced to maptroid's data shapes. This command is the "sink" that
loads such a bundle into the database. It is the maptroid-side half of
asmr's extractor track item 08 (world assembly + ingestion).

What it does
------------
- get_or_create a World (by slug) — re-running OVERWRITES, idempotent.
- get_or_create one Zone per ROM area (Crateria..Tourian, by area_idx).
- get_or_create one Room per bundle room (by world + key), writing the
  asmr-owned fields into Room.data: zone.bounds, holes, geometry.inner.
- normalize() each zone, then the world, so coordinates are zoned.

What it deliberately does NOT do
--------------------------------
- Doors. The bundle ships per-room `doors`, but maptroid's stored door
  `dir` convention is mirrored vs the bundle's and maptroid omits
  elevator-connection doors (see asmr extractor backlog item 20). Until
  that migration lands, writing doors would corrupt curated data — so
  this loader writes none. maptroid derives doors itself elsewhere.
- Elevators. World-level; left to maptroid. (bundle has a top-level
  `elevators` list — not consumed here, see item 20 open question.)
- Enemies. PLM enemies/sprites still deferred (asmr extractor item 06).
  Items (the 100 vanilla pickups) ARE loaded — see _load_items.
- Image pyramids. The bundle ships no per-room PNGs, so there is
  nothing to tile. Pyramid generation stays with maptroid's existing
  `scripts/2-process_sm.py` / `process_zone` path.

Safety
------
Defaults to world-slug `vanilla` (the bundle's own `world` field), i.e.
a SCRATCH world — it does NOT touch the curated `super-metroid` world.
This is the item-08 round-trip check: load into a scratch world, diff
against the real one. Point `--world-slug super-metroid` at the real
world only deliberately, and not before backlog item 20 is resolved.

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

# ROM area index -> maptroid zone name. Matches scripts/_new_world.py.
AREA_ZONE_NAMES = [
    'Crateria',      # 0
    'Brinstar',      # 1
    'Norfair',       # 2
    'Wrecked Ship',  # 3
    'Maridia',       # 4
    'Tourian',       # 5
]
AREA_BASE_SLUGS = tuple(slugify(n) for n in AREA_ZONE_NAMES)


def _load_arrangement(bundle_path):
    """Read the sibling `<bundle>.arrangement.json`, or return None.

    Sidecar spec: asmr/docs/backlog/extractor/22-arrangement-override-schema.md.
    Authored by hand (or by asmr extractor/23-24's UI, once it lands) and
    consumed here. asmr's build_bundle validates it on emit; we re-validate
    keys we touch but tolerate missing pointers (logged, inert) since the
    bundle's room set is the source of truth for which rooms exist.
    """
    arr_path = bundle_path.with_suffix('').with_suffix('.arrangement.json')
    if not arr_path.exists():
        return None
    return json.loads(arr_path.read_text())


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
        arrangement = _load_arrangement(path)

        slug = opts['world_slug'] or slugify(bundle['world'])
        name = opts['world_name'] or f'{bundle["world"]} (asmr import)'
        rooms = bundle.get('rooms') or []

        self.stdout.write(
            f'bundle: {path}  world={bundle.get("world")!r}  '
            f'rooms={len(rooms)}  extractor={bundle.get("extractor_version")}')
        if arrangement is not None:
            self.stdout.write(
                f'arrangement: {len(arrangement.get("subzones") or [])} subzone(s), '
                f'{len(arrangement.get("zone_world_bounds") or {})} zone bound(s), '
                f'{len(arrangement.get("room_zone_assignments") or {})} room reassignment(s), '
                f'{len(arrangement.get("room_zone_bounds") or {})} room bound(s)')
        if slug == 'super-metroid':
            self.stdout.write(self.style.WARNING(
                '  !! targeting the curated super-metroid world — '
                'this overwrites hand-built data.'))

        try:
            with transaction.atomic():
                self._load(bundle, slug, name, rooms, arrangement)
                if opts['dry_run']:
                    self.stdout.write(self.style.WARNING('dry-run — rolling back.'))
                    transaction.set_rollback(True)
        except Exception as exc:  # surface, don't half-commit
            raise CommandError(f'load failed: {exc}')

        if not opts['dry_run']:
            self.stdout.write(self.style.SUCCESS('done.'))

    def _load(self, bundle, slug, name, rooms, arrangement):
        world, created = World.objects.get_or_create(
            slug=slug, defaults={'name': name})
        # asmr-loaded worlds are full vanilla replicas — surface them in the
        # world listing the same way the curated super-metroid world is. The
        # original `hidden: True` came from an earlier scratch-only design.
        if world.data.get('hidden'):
            world.data['hidden'] = False
            world.save()
        self.stdout.write(
            f'world: {"created" if created else "reusing"} '
            f'{world.name!r} (id={world.id}, slug={world.slug})')

        arr = arrangement or {}
        subzone_slugs = list(arr.get('subzones') or [])
        zone_world_bounds = arr.get('zone_world_bounds') or {}
        room_zone_assignments = {k.upper(): v
                                 for k, v in (arr.get('room_zone_assignments') or {}).items()}
        room_zone_bounds = {k.upper(): v
                            for k, v in (arr.get('room_zone_bounds') or {}).items()}

        # Validate subzone slugs (asmr's build_bundle already does this on emit,
        # but a sidecar can land here without having gone through that path).
        for sz in subzone_slugs:
            if '__' not in sz or sz.split('__', 1)[0] not in AREA_BASE_SLUGS:
                raise CommandError(
                    f'arrangement: subzone {sz!r} must be <area>__<suffix> '
                    f'with <area> in {AREA_BASE_SLUGS}')
        subzone_set = set(subzone_slugs)

        # Group rooms by ROM area for default zone assignment.
        by_area = {}
        for rec in rooms:
            by_area.setdefault(rec['area_idx'], []).append(rec)

        # Track which zone slugs the arrangement explicitly positions —
        # those skip normalize() (positions are authoritative).
        overridden_zone_slugs = set(zone_world_bounds.keys())

        # Create the six base area zones.
        zone_by_slug = {}
        zone_by_area = {}
        for area_idx in sorted(by_area):
            members = by_area[area_idx]
            zname = (AREA_ZONE_NAMES[area_idx] if 0 <= area_idx < len(AREA_ZONE_NAMES)
                     else f'area-{area_idx}')
            zslug = slugify(zname)
            zone, zcreated = Zone.objects.get_or_create(
                world=world, slug=zslug, defaults={'name': zname})
            if zslug in zone_world_bounds:
                zone.data['world'] = {'bounds': list(zone_world_bounds[zslug])}
            else:
                # Default behavior: top-left from min room xy; w/h via normalize().
                zx = min(r['xy'][0] for r in members)
                zy = min(r['xy'][1] for r in members)
                zone.data['world'] = {'bounds': [zx, zy, 1, 1]}
            zone.save()
            zone_by_slug[zslug] = zone
            zone_by_area[area_idx] = zone
            self.stdout.write(
                f'  zone {area_idx}: {"created" if zcreated else "reusing"} '
                f'{zname!r}  {len(members)} rooms')

        # Create subzones declared by the arrangement. These are positioned
        # exclusively by zone_world_bounds (no default-from-members fallback
        # — rooms are assigned individually, so a subzone with no
        # zone_world_bounds entry has no defensible position).
        for sz in subzone_slugs:
            zname = sz  # display name = slug for synthesized subzones
            zone, zcreated = Zone.objects.get_or_create(
                world=world, slug=sz, defaults={'name': zname})
            if sz in zone_world_bounds:
                zone.data['world'] = {'bounds': list(zone_world_bounds[sz])}
            elif not zone.data.get('world'):
                # No override and no prior bounds — park at origin; world.normalize
                # will at least keep it in-frame. Loud warning so the human knows
                # to fill in zone_world_bounds[sz].
                self.stdout.write(self.style.WARNING(
                    f'  subzone {sz!r} has no zone_world_bounds entry; '
                    f'positioning at (0,0,1,1) — fill it in to fix layout'))
                zone.data['world'] = {'bounds': [0, 0, 1, 1]}
            zone.save()
            zone_by_slug[sz] = zone
            self.stdout.write(
                f'  subzone: {"created" if zcreated else "reusing"} {sz!r}')

        # Validate room_zone_assignments now that we know which subzones exist.
        for ptr, target in room_zone_assignments.items():
            if target not in subzone_set:
                raise CommandError(
                    f'arrangement: room_zone_assignments[{ptr}] = {target!r} — '
                    f'target subzone is not in arrangement.subzones')
            if ptr not in room_zone_bounds:
                # See build_bundle.validate_arrangement for the rationale.
                raise CommandError(
                    f'arrangement: room_zone_assignments[{ptr}] is set but '
                    f'room_zone_bounds[{ptr}] is missing — a reassigned room '
                    f'must declare its zone-local bounds')

        # Rooms. key = "<world-slug>_<POINTER>.png" — maptroid's convention.
        n_created = 0
        n_reassigned = 0
        n_bounds_overridden = 0
        for rec in rooms:
            ptr = rec['pointer'].upper()
            key = f'{slug}_{ptr}.png'
            target_slug = room_zone_assignments.get(ptr)
            if target_slug is not None:
                zone = zone_by_slug[target_slug]
                n_reassigned += 1
            else:
                zone = zone_by_area[rec['area_idx']]
            try:
                room = Room.objects.get(world=world, key=key)
            except Room.DoesNotExist:
                room = Room(world=world, key=key)
                n_created += 1
            room.zone = zone
            room.name = room.name or rec.get('area')  # don't clobber curated names
            data = room.data or {}
            # asmr-owned fields only — merge, preserving any maptroid-side keys.
            data.setdefault('zone', {})
            if ptr in room_zone_bounds:
                data['zone']['bounds'] = list(room_zone_bounds[ptr])
                n_bounds_overridden += 1
            else:
                data['zone']['bounds'] = [rec['xy'][0], rec['xy'][1],
                                          rec['width'], rec['height']]
            data['holes'] = rec.get('holes') or []
            data.setdefault('geometry', {})
            data['geometry']['inner'] = rec.get('geometries') or []
            room.data = data
            room.save()  # recomputes geometry.screens / geometry.outer
        self.stdout.write(
            f'  rooms: {n_created} created, '
            f'{len(rooms) - n_created} updated')
        if n_reassigned or n_bounds_overridden:
            self.stdout.write(
                f'  arrangement applied: {n_reassigned} room reassignment(s), '
                f'{n_bounds_overridden} room bound override(s)')

        # Coordinates: zone.normalize() shifts rooms to zone-relative and
        # sets each zone's w/h. Skip normalize for zones the arrangement
        # positions explicitly — those bounds are authoritative.
        for zslug, zone in zone_by_slug.items():
            if zslug in overridden_zone_slugs:
                continue
            zone.normalize()
        w, h = world.normalize()
        self.stdout.write(f'  normalized — world is {w}x{h} cells')

        self._load_items(world, rooms)

    def _load_items(self, world, rooms):
        """Wipe-and-rewrite items for this world. The frontend's MapView
        bails (ready === false) when world_items.length is 0, so without
        this the viewer would never mount for an asmr-loaded world."""
        # Idempotent: blow away the previous import, then rewrite.
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
                Item.objects.create(
                    room=room,
                    zone=room.zone,
                    data={
                        'type': it['type'],
                        'room_xy': it['room_xy'],
                        'modifier': it.get('modifier'),
                    },
                )
                n += 1
        self.stdout.write(f'  items: {n} loaded')
