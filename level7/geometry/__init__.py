"""Geometry helpers: placement transforms, polygon utilities, search approximations."""
from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from ..model import Placement, Point


def transform_points(pts: list[Point], rotation: float, mirrored: bool, dx: float = 0.0, dy: float = 0.0) -> list[Point]:
    """Mirror about Y axis (x -> -x) if requested, rotate CCW by ``rotation`` deg, translate."""
    a = math.radians(rotation)
    c, s = math.cos(a), math.sin(a)
    # snap exact multiples of 90 deg to avoid 1e-16 noise
    if abs(rotation % 90.0) < 1e-12:
        c, s = round(c), round(s)
    out = []
    for x, y in pts:
        if mirrored:
            x = -x
        out.append((c * x - s * y + dx, s * x + c * y + dy))
    return out


def placement_points(pts: list[Point], pl: Placement) -> list[Point]:
    return transform_points(pts, pl.rotation, pl.mirrored, pl.x, pl.y)


def bbox(pts: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def polygon(pts: list[Point], holes: list[list[Point]] | None = None) -> Polygon:
    p = Polygon(pts, holes or [])
    if not p.is_valid:
        p = p.buffer(0)
    return orient(p) if isinstance(p, Polygon) else p


def ring_area(pts: list[Point]) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def polyline_length(pts: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def grain_angle(pts: list[Point]) -> float | None:
    """Angle (deg, 0..180) of the longest segment of a grain-line polyline."""
    best = None
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        if d > 1e-6 and (best is None or d > best[0]):
            best = (d, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0)
    return None if best is None else best[1]


def search_polygon(pts: list[Point], spacing: float, tolerance: float) -> tuple[list[Point], float]:
    """Outward approximation used for searching placements.

    Returns a simplified polygon that fully contains the original cut contour grown by
    ``spacing / 2``. Construction: buffer by spacing/2 + tolerance, simplify with
    ``tolerance`` (Douglas-Peucker moves the boundary by at most ``tolerance``).
    The achieved maximum deviation (Hausdorff distance to the grown original) is returned.
    """
    base = Polygon(pts)
    if not base.is_valid:
        base = base.buffer(0)
    grow = spacing / 2.0
    target = base.buffer(grow, join_style=2, mitre_limit=2.0) if grow > 0 else base
    if tolerance <= 0:
        poly = target
    else:
        poly = base.buffer(grow + tolerance, join_style=2, mitre_limit=2.0).simplify(tolerance, preserve_topology=True)
        if not poly.contains(target):
            poly = poly.union(target).simplify(0, preserve_topology=True)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    ext = list(poly.exterior.coords)[:-1]
    dev = poly.exterior.hausdorff_distance(LineString(list(target.exterior.coords)))
    return ext, dev
