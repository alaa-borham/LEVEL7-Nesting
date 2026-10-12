"""No-fit-polygon placement primitives on integer coordinates (pyclipper / Clipper 6).

Conventions
-----------
* Polygons are lists of integer (x, y) at SCALE units per millimetre.
* An orbiting polygon B is normalised so that its bounding box starts at (0, 0);
  a position ``t`` means B translated by ``t``.
* NFP(A, B) = MinkowskiDiff(B, A): the set of t for which A and B+t overlap.
  Clipper returns the Minkowski sum of the outlines; inner rings are dropped, so the
  result is conservative (positions fully enclosed by A are never used).
"""
from __future__ import annotations

import pyclipper

SCALE = 100  # 0.01 mm resolution


def to_int(pts, scale=SCALE):
    return [(int(round(x * scale)), int(round(y * scale))) for x, y in pts]


def nfp(fixed, orbiting):
    paths = pyclipper.MinkowskiDiff(orbiting, fixed)
    if not paths:
        return []
    areas = [pyclipper.Area(p) for p in paths]
    big = max(range(len(paths)), key=lambda i: abs(areas[i]))
    sign = areas[big] > 0
    return [p for p, a in zip(paths, areas) if (a > 0) == sign]


def translate(paths, dx, dy):
    return [[(x + dx, y + dy) for x, y in p] for p in paths]


def feasible_region(ifp_rect, forbidden_paths):
    """IFP rectangle minus union of forbidden paths -> list of polygons (with holes as separate paths)."""
    if not forbidden_paths:
        return [ifp_rect]
    pc = pyclipper.Pyclipper()
    pc.AddPath(ifp_rect, pyclipper.PT_SUBJECT, True)
    try:
        pc.AddPaths(forbidden_paths, pyclipper.PT_CLIP, True)
    except pyclipper.ClipperException:
        good = [p for p in forbidden_paths if len(p) >= 3]
        if good:
            pc.AddPaths(good, pyclipper.PT_CLIP, True)
    return pc.Execute(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def point_in_any(pt, paths) -> bool:
    """True if pt strictly inside the union of ``paths`` (non-zero rule)."""
    wn = 0
    for p in paths:
        r = pyclipper.PointInPolygon(pt, p)
        if r == -1:
            return False  # on boundary of some path -> treat as touching
        if r == 1:
            wn += 1 if pyclipper.Orientation(p) else -1
    return wn != 0
