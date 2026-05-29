import cv2
from django.conf import settings
import functools
import numpy as np
import os
from PIL import Image, ImageDraw

from maptroid.doors import draw_doors
# Deferred: maptroid.dzi imports `deepzoom`, which isn't installable from
# the current PyPI; with --skip-dzi we never actually call png_to_dzi, so
# don't take the import error at module-load time.
try:
    from maptroid.dzi import png_to_dzi
except ModuleNotFoundError:  # pragma: no cover
    def png_to_dzi(*args, **kwargs):
        raise ModuleNotFoundError(
            "deepzoom not installed — use --skip-dzi or install the real "
            "github.com/openzoom/deepzoom.py.")
from maptroid.icons import get_icons, MAP_OPERATIONS, get_template_icons
from maptroid.utils import mkdir
import unrest_image as img
import urcv


def set_transparency(image, dest=None, bg_color=(0, 0, 0)):
    if type(image) == str:
        image = Image.open(image)
    image = image.convert("RGBA")
    array = np.array(image, dtype=np.ubyte)
    image.close()
    mask = (array[:,:,:3] == bg_color).all(axis=2)
    alpha = np.where(mask, 0, 255)
    array[:,:,-1] = alpha
    result = Image.fromarray(np.ubyte(array))
    if dest:
        result.save(dest, "PNG")
    return result


def get_occupied_world_xys(target_zone):
    occupied_xy_map = {}
    for zone in target_zone.world.zone_set.all():
        if zone.data.get('hidden'):
            continue
        zone_x, zone_y, _, _ = zone.data['world']['bounds']
        for room in zone.room_set.all():
            holes = room.data.get('holes') or []
            room_x, room_y, width, height = room.data['zone']['bounds']
            for dx in range(width):
                for dy in range(height):
                    if not [dx, dy] in holes:
                        zone_xy = f'{zone_x + room_x+dx},{zone_y + room_y+dy}'
                        occupied_xy_map[zone_xy] = room.id
    return occupied_xy_map

def to_media_url(path, *args):
    return os.path.join(settings.MEDIA_URL, path.split('/.media/')[-1], *args)

@functools.lru_cache
def get_vitality_layer_1(zone_slug):
    hires_dir = os.path.join(settings.SINK_DIR, '_hires-vitality/processed/')
    path = os.path.join(hires_dir, f'{zone_slug}.png')
    return urcv.force_alpha(cv2.imread(path))

def process_zone(zone, skip_dzi=False):
    if zone.data.get("hidden"):
        return
    zone.normalize()
    world = zone.world
    CACHE_DIR = mkdir(settings.MEDIA_ROOT, f'sm_cache/{world.slug}')
    ROOM_DIR = mkdir(settings.MEDIA_ROOT, f'sm_room/{world.slug}')
    LAYER_DIR = mkdir(settings.MEDIA_ROOT, f'sm_zone/{world.slug}/layer-1')
    WALLS_DIR = mkdir(settings.MEDIA_ROOT, f'sm_zone/{world.slug}/walls')
    BTS_DIR = mkdir(settings.MEDIA_ROOT, f'sm_zone/{world.slug}/bts')
    PLM_DIR = mkdir(settings.MEDIA_ROOT, f'sm_zone/{world.slug}/plm_enemies')

    rooms = zone.room_set.all()

    # Make note of which xys to punch out in the holes
    occupied_xy_map = get_occupied_world_xys(zone)
    kernel3 = np.ones((3,3), dtype=np.uint8)

    def make_layered_zone_image(zone, layers, dest):
        zone_x, zone_y, zw, zh = zone.data['world']['bounds']
        zone_image = np.zeros((zh * 256, zw * 256, 4), dtype=np.uint8)
        layers_dir = mkdir(CACHE_DIR, '+'.join(layers))

        for room in rooms:
            room_x, room_y, width, height = room.data['zone']['bounds']
            room_image = np.zeros((int(height) * 256, int(width) * 256, 4), dtype=np.uint8)
            if 'layer-2' in layers:
                room_image[:,:] = (17, 17, 17, 255)

            # this allows the clear_holes preference to be set from the top down
            # some maps (eg ascent) look better if filled in a bit more
            zone_clear_holes = world.data.get('clear_holes') or zone.data.get('clear_holes')
            room_clear_holes = zone_clear_holes or room.data.get('clear_holes')

            holes = []
            for [dx, dy] in room.data.get('holes') or []:
                zone_xy = f'{zone_x + room_x + dx},{zone_y + room_y + dy}'
                if room_clear_holes or zone_xy in occupied_xy_map:
                    holes.append([dx, dy])

            for layer in layers:
                is_door_layer = layer == 'layer-1' and 'doors' in room.data
                path = os.path.join(settings.SINK_DIR, f'{world.slug}/{layer}/{room.key}')
                layer_dir = mkdir(CACHE_DIR, layer)
                layer_path = os.path.join(layer_dir, room.key)

                cutout_bg = layer == 'layer-2'
                if room.data.get('invert_layers'):
                    # "fire flea" rooms have their layers switched in smile
                    cutout_bg = layer == 'layer-1'
                if 'layer-1' in layers and world.slug == 'vitality':
                    # Use ingame scans instead
                    bounds = 256 * np.array(room.data['zone']['bounds'], dtype=np.uint32)
                    hires_zone_image = get_vitality_layer_1(zone.slug)
                    room_image = urcv.transform.crop(hires_zone_image, bounds).copy()
                    cv2.imwrite(layer_path, room_image)
                    continue
                elif not os.path.exists(path):
                    print(f'skipping {room.key} {layer} because file DNE')
                else:
                    layer_image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                    if np.sum(layer_image) == 0:
                        # blank images don't need to be processed
                        # they also cause errors because they are grayscale
                        continue
                    layer_image = urcv.force_alpha(layer_image)
                    if cutout_bg and 'inner' in room.data['geometry']:
                        for polygon in room.data['geometry']['inner']:
                            xys = [(p[0]*256, p[1]*256) for p in polygon['exterior']]
                            interiors = polygon['interiors']
                            interiors = [[(p[0]*256, p[1]*256) for p in shape] for shape in interiors]
                            urcv.draw.polygon(
                                layer_image,
                                xys,
                                fill=(0,0,0,0),
                                interiors=interiors,
                            )
                    urcv.remove_color_alpha(layer_image, (0, 0, 0))
                    forced_front = room.data.get('invert_layers') and layer == 'layer-2'
                    if layer == 'layer-1' or forced_front:
                        mask = cv2.cvtColor(layer_image, cv2.COLOR_BGR2GRAY)
                        _, mask = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)

                        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel3, iterations=1)
                        canvas = layer_image.copy()
                        canvas[(mask==255)] = [0,0,0,255]
                        urcv.draw.paste_alpha(canvas, layer_image, 0, 0)
                        layer_image = canvas
                    if is_door_layer:
                        draw_doors(layer_image, room.data['doors'], zone.world.slug)
                    cv2.imwrite(layer_path, layer_image)
                    urcv.draw.paste_alpha(room_image, layer_image, 0, 0)

            if room.data.get('geometry_override'):
                mask = np.zeros(room_image.shape[:2], dtype=np.uint8)
                points = [[int(256 * i) for i in xy] for xy in room.data['geometry_override']]
                points.append(points[0])
                points = np.array([[points]])
                cv2.fillPoly(mask, points, (255))
                room_image = cv2.bitwise_and(room_image, room_image, mask = mask)
                room_image = cv2.polylines(room_image, points, True, (255, 0, 0), 2)
            else:
                for x, y in holes:
                    room_image[y*256:(y+1) * 256,x*256:(x+1) * 256,:] = [0,0,0,0]

            cv2.imwrite(os.path.join(layers_dir, room.key), room_image)
            urcv.draw.paste_alpha(zone_image, room_image, room_x * 256, room_y * 256)

        cv2.imwrite(dest, zone_image)
        if not skip_dzi:
            png_to_dzi(dest)
            if zone.world.slug == 'vitality' and 'layer-1' in layers:
                os.unlink(dest)

    zone.normalize()

    # removing old dzi keys as they are no longer used
    for key in list(zone.data.keys()):
        if key.endswith('dzi'):
            zone.data.pop(key)

    zone_x, zone_y, zw, zh = zone.data['world']['bounds']
    if zw > 70 or zh > 70:
        print(f'WARNING: skipping dzis for {zone.name} because bounds are too large: {zw}x{zh}')
    elif not skip_dzi:
        make_layered_zone_image(zone, ['layer-2', 'layer-1'], os.path.join(LAYER_DIR, f'{zone.slug}.png'))
        make_layered_zone_image(zone, ['bts'], os.path.join(BTS_DIR, f'{zone.slug}.png'))
        make_layered_zone_image(zone, ['plm_enemies'], os.path.join(PLM_DIR, f'{zone.slug}.png'))

        walls_dest = os.path.join(WALLS_DIR, f'{zone.slug}.png')
        make_walls_image(zone, walls_dest)
        png_to_dzi(walls_dest)

    zone.save()


DOOR_DELTAS = {
    'left': list(zip((0,0,0,0), range(4))),
    'right': list(zip((0,0,0,0), range(4))),
    'up': list(zip(range(4), (0,0,0,0))),
    'down': list(zip(range(4), (0,0,0,0))),
}


def make_walls_image(zone, dest):
    zone_x, zone_y, zw, zh = zone.data['world']['bounds']
    zone_image = np.zeros((zh * 256, zw * 256, 4), dtype=np.uint8)

    color = (128, 128, 128, 255)
    color_alpha = (128, 128, 128, 128)
    icons = {
        **get_icons('block', operations=MAP_OPERATIONS),
        **get_icons('block-alt', operations=MAP_OPERATIONS),
        **get_icons('misc-spikes', operations=MAP_OPERATIONS),
        **get_icons('cre-hex', operations=MAP_OPERATIONS),
        **get_template_icons(),
    }
    for room in zone.room_set.all():
        if 'inner' not in room.data['geometry']:
            continue
        room_x, room_y, room_w, room_h = room.data['zone']['bounds']
        def room_xy_to_zone_xy(xy):
            return [256 * (room_x + xy[0]), 256 * (room_y + xy[1])]
        for geo in room.data['geometry']['inner']:
            pts = [room_xy_to_zone_xy(p) for p in geo['exterior']]
            interiors = geo['interiors']
            interiors = [[room_xy_to_zone_xy(p) for p in shape] for shape in interiors]
            urcv.draw.polygon(
                zone_image,
                pts,
                fill=color_alpha,
                stroke=color,
                interiors=interiors,
            )
        stamp_map = {}
        def reverse_rectangles(cre_map):
            out = {}
            for category, bounds_list in cre_map.items():
                for x0, y0, w, h in bounds_list:
                    for dx in range(w):
                        for dy in range(h):
                            x = 16 * (x0 + dx + room_x * 16)
                            y = 16 * (y0 + dy + room_y * 16)
                            out[(x, y)] = category
            return out
        stamp_map.update(reverse_rectangles(room.data.get('cre_hex', {})))
        stamp_map.update(reverse_rectangles(room.data.get('cre', {})))
        for [x0, y0, w, h, category] in room.data.get('cre_overrides', []):
            for dx in range(w):
                for dy in range(h):
                    x = 16 * (x0 + dx + room_x * 16)
                    y = 16 * (y0 + dy + room_y * 16)
                    stamp_map[(x, y)] = category

        doors = []
        for x, y, orientation, alpha in room.data.get('doors', []):
            for dx, dy in DOOR_DELTAS[orientation]:
                zx = 16 * (x + dx + room_x * 16)
                zy = 16 * (y + dy + room_y * 16)
                stamp_map.pop((zx, zy), None)
            doors.append([x+room_x*16, y+room_y*16, orientation, alpha])

        for sxy, type_ in room.data.get('plm_overrides', {}).items():
            if type_ not in icons:
                if type_ not in ['elevator', 'wipe']:
                    print("WARNING: unknown type", type_)
                continue
            [x, y] = tuple([int(i) for i in sxy.split(',')])
            h, w = [i // 16 for i in icons[type_].shape[:2]]
            for dx in range(w):
                for dy in range(h):
                    zx = 16 * (x + dx + room_x * 16)
                    zy = 16 * (y + dy + room_y * 16)
                    stamp_map.pop((zx, zy), None)
            zxy = (16 * (x + room_x * 16), 16 * (y + room_y * 16))
            stamp_map[zxy] = type_
        zone_image = draw_doors(zone_image, doors, 'super-metroid')

        skip = ['empty', 'block']
        stamp_map = { k: v for k, v in stamp_map.items() if v not in skip }
        for (x, y), category in stamp_map.items():
            if not category:
                raise ValueError("Category does not exist. Assign value at /app/smilesprite")
            urcv.draw.paste_alpha(zone_image, icons[category], x, y)
    cv2.imwrite(dest, zone_image)
