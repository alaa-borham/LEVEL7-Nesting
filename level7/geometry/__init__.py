"""Geometry helpers: placement transforms, polygon utilities, search approximations."""
from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from ..model import Placement, Point


def transform_points(pts: list[Point], rotation: float, mirrored: bool, dx: float = 0.0, dy: float = 0.0,
                     sx: float = 1.0, sy: float = 1.0) -> list[Point]:
    """Mirror about Y axis (x -> -x) if requested, rotate CCW by ``rotation`` deg, scale by (sx, sy) in marker
    axes (shrinkage), translate."""
    a = math.radians(rotation)
    c, s = math.cos(a), math.sin(a)
    # snap exact multiples of 90 deg to avoid 1e-16 noise
    if abs(rotation % 90.0) < 1e-12:
        c, s = round(c), round(s)
    out = []
    for x, y in pts:
        if mirrored:
            x = -x
        out.append((sx * (c * x - s * y) + dx, sy * (s * x + c * y) + dy))
    return out


def placement_points(pts: list[Point], pl: Placement) -> list[Point]:
    return transform_points(pts, pl.rotation, pl.mirrored, pl.x, pl.y, pl.sx, pl.sy)


def grow_rect(poly, ax: float, ay: float):
    """Exact Minkowski sum of a shapely polygon with the rectangle [-ax, ax] x [-ay, ay]."""
    if ax <= 0 and ay <= 0:
        return poly
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union
    parts = [poly]
    for ring in [poly.exterior]:
        c = list(ring.coords)
        for (x0, y0), (x1, y1) in zip(c, c[1:]):
            parts.append(MultiPoint([(x + u, y + v) for x, y in ((x0, y0), (x1, y1))
                                     for u in (-ax, ax) for v in (-ay, ay)]).convex_hull)
    out = unary_union(parts)
    if out.geom_type != "Polygon":
        out = max(out.geoms, key=lambda g: g.area)
    return Polygon(out.exterior)


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


def search_polygon(pts: list[Point], spacing: float, tolerance: float,
                   rect: tuple[float, float] = (0.0, 0.0)) -> tuple[list[Point], float]:
    """Outward approximation used for searching placements.

    Returns a simplified polygon that fully contains the original cut contour grown by
    ``spacing / 2``. Construction: buffer by spacing/2 + tolerance, simplify with
    ``tolerance`` (Douglas-Peucker moves the boundary by at most ``tolerance``). ``rect`` = (ax, ay) additionally
    grows the shape by ax along x and ay along y (directional buffer, marker axes).
    The achieved maximum deviation (Hausdorff distance to the grown original) is returned.
    """
    base = Polygon(pts)
    if not base.is_valid:
        base = base.buffer(0)
    grow = spacing / 2.0
    target = base.buffer(grow, join_style=2, mitre_limit=2.0) if grow > 0 else base
    target = grow_rect(target, *rect)
    if tolerance <= 0:
        poly = target
    else:
        src, g = (base, grow + tolerance) if rect[0] <= 0 and rect[1] <= 0 else (target, tolerance)
        poly = src.buffer(g, join_style=2, mitre_limit=2.0).simplify(tolerance, preserve_topology=True)
        if not poly.contains(target):
            poly = poly.union(target).simplify(0, preserve_topology=True)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    ext = list(poly.exterior.coords)[:-1]
    dev = poly.exterior.hausdorff_distance(LineString(list(target.exterior.coords)))
    return ext, dev


def lay_direction(grain_angle_deg: float | None, pl: Placement) -> int | None:
    """+1 if the placed copy's grain points along +x (marker length), -1 if turned 180° against it, None if
    unknown or across the length. Mirrored copies in their base orientation also give +1 (see grain_rotations)."""
    if grain_angle_deg is None:
        return None
    a = math.radians(grain_angle_deg)
    (vx, _), = transform_points([(math.cos(a), math.sin(a))], pl.rotation, pl.mirrored)
    return 1 if vx > 1e-6 else -1 if vx < -1e-6 else None
