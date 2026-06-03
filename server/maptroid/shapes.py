from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
from shapely.ops import unary_union

def _square(x, y):
    return Polygon([
        [x, y],
        [x+1, y],
        [x+1, y+1],
        [x, y+1],
    ])

def get_screens(room):
    screens = []
    _x, _y, width, height = room.data['zone']['bounds']
    if type(width) == float:
        room.data['zone']['bounds'] = [int(i) for i in room.data['zone']['bounds']]
        _x, _y, width, height = room.data['zone']['bounds']
    for x in range(width):
        for y in range(height):
            holes = room.data.get('holes') or []
            if not [x, y] in holes:
                screens.append([x, y])
    return screens

def get_room_walls(room):
    override = room.data.get('geometry_override')
    if override:
        # asmr emits geometry_override in two shapes (asmr extractor/27):
        #   - exterior ring: a single boundary [[x, y], ...]
        #   - full replace : [{exterior, interiors}, ...] — the precise interior
        #     polygons (legacy hand-authored geometry). Build the wall outline
        #     from those polygons (with their holes) rather than treating the
        #     list of dicts as a coordinate ring.
        if isinstance(override[0], dict):
            polygons = [Polygon(g['exterior'], g.get('interiors') or [])
                        for g in override]
        else:
            polygons = [Polygon(override)]
    else:
        polygons = [_square(x, y) for x, y in get_screens(room)]
    return polygons_to_geometry(polygons)

def polygons_to_geometry(polygons, isolations=[], external=None):
    multipolygon = unary_union(polygons)
    if external is not None:
        multipolygon = multipolygon.intersection(Polygon(external))

    # intersection can turn it into a geometry collection
    if not multipolygon.is_empty and isinstance(multipolygon, GeometryCollection):
        multipolygon = MultiPolygon(geo_object for geo_object in multipolygon.geoms
                                    if isinstance(geo_object, (Polygon, MultiPolygon)))

    # unary union and difference has a tendency to convert multipolygon back into a polygon
    if isinstance(multipolygon, Polygon):
        multipolygon = MultiPolygon([multipolygon])
    for shape in isolations:
        multipolygon = multipolygon.difference(Polygon(shape))
    if isinstance(multipolygon, Polygon):
        multipolygon = MultiPolygon([multipolygon])

    return [
        {
            'exterior': [list(p) for p in polygon.exterior.coords[:-1]],
            'interiors': [[list(p) for p in i.coords[:-1]] for i in polygon.interiors],
        }
        for polygon in multipolygon.geoms
    ]

# TODO I tried to reduce polygons by removing redundant points, bus p2js didn't seem to like it.
def reduce_polygon(points):
    if not points:
        return points
    polygon = Polygon(points)
    starting_area = polygon.area
    polygon = polygon.simplify(0.001)
    assert(starting_area == polygon.area)
    print(len(points), len(polygon.exterior.coords))
    return [list(p) for p in polygon.exterior.coords]