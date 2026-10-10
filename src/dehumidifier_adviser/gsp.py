"""Grid Supply Point (GSP) region lookup from coordinates."""

import math
from itertools import pairwise

# Points just outside every region (e.g. on a coastline smoothed by simplification) are assigned
# to the nearest region if they are within this distance of its boundary.
NEAREST_REGION_MAX_DISTANCE_KM = 10.0

_KM_PER_DEGREE_LATITUDE = 111.32


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting test for whether a point lies inside a closed linear ring."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygons(geometry: dict) -> list[list[list[list[float]]]]:
    """Return a geometry's polygons, each a list of rings (outer ring first, then holes)."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    return geometry["coordinates"]


def _contains(geometry: dict, lon: float, lat: float) -> bool:
    for outer, *holes in _polygons(geometry):
        if _point_in_ring(lon, lat, outer) and not any(_point_in_ring(lon, lat, hole) for hole in holes):
            return True
    return False


def _distance_to_boundary_km(geometry: dict, lon: float, lat: float) -> float:
    """Approximate distance from a point to the nearest edge of a geometry, in kilometres."""
    km_per_degree_longitude = _KM_PER_DEGREE_LATITUDE * math.cos(math.radians(lat))
    best = math.inf
    for polygon in _polygons(geometry):
        for ring in polygon:
            for (x1, y1), (x2, y2) in pairwise(ring):
                # Project onto a local flat plane in km, centred on the point
                ax, ay = (x1 - lon) * km_per_degree_longitude, (y1 - lat) * _KM_PER_DEGREE_LATITUDE
                bx, by = (x2 - lon) * km_per_degree_longitude, (y2 - lat) * _KM_PER_DEGREE_LATITUDE
                dx, dy = bx - ax, by - ay
                length_squared = dx * dx + dy * dy
                t = 0.0 if length_squared == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
                best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def find_gsp(latitude: float, longitude: float, regions: dict) -> str | None:
    """Find the GSP region letter (A-P) covering a location.

    Args:
        latitude: Location latitude
        longitude: Location longitude
        regions: GeoJSON FeatureCollection with one feature per GSP region, each having a ``gsp`` property

    Returns:
        The GSP region letter, or None if the location is not in (or near) any region
    """
    features = regions["features"]
    for feature in features:
        if _contains(feature["geometry"], longitude, latitude):
            return feature["properties"]["gsp"]

    distance, nearest = min(
        (_distance_to_boundary_km(feature["geometry"], longitude, latitude), feature["properties"]["gsp"])
        for feature in features
    )
    return nearest if distance <= NEAREST_REGION_MAX_DISTANCE_KM else None


class LocationOutsideGridSupplyAreaError(ValueError):
    """Raised when a location is not covered by any GSP region (i.e. outside England, Scotland and Wales)."""


def require_gsp(latitude: float, longitude: float, regions: dict) -> str:
    """Find the GSP region letter (A-P) covering a location, raising if there is none.

    Args:
        latitude: Location latitude
        longitude: Location longitude
        regions: GeoJSON FeatureCollection with one feature per GSP region, each having a ``gsp`` property

    Returns:
        The GSP region letter

    Raises:
        LocationOutsideGridSupplyAreaError: If the location is not in (or near) any region
    """
    gsp = find_gsp(latitude, longitude, regions)
    if gsp is None:
        raise LocationOutsideGridSupplyAreaError(
            f"Location ({latitude:.4f}, {longitude:.4f}) is outside the Grid Supply Point regions. "
            "Only locations in England, Scotland and Wales are supported."
        )
    return gsp
