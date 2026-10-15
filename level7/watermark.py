"""Watermark on the pieces (a logo or a word) - on screen and in printing only, never in the cutting / plotter
exports (PLT, DXF, ISO, SCB).

The settings live in ``Project.watermark`` (saved in the .l7n project, the logo embedded). Where it goes is worked
out once per piece size in pattern coordinates and moves with every copy of the piece:

* ``align`` "grain": the logo reads along the grain line (lengthways in the marker); "long": along the piece's
  longest side.
* ``position``: centre / top / bottom / left / right of the piece, in the logo's own reading direction.
* ``size_pct``: logo width in % of the piece (along the reading direction), at most ``max_mm``; made smaller until it
  lies inside the piece with a small margin. Pieces too small for it get none.
* mirrored copies show the logo readable (not mirror-written); with ``upright`` copies turned 180 deg too.
"""
from __future__ import annotations

import math
from functools import lru_cache

from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import polylabel

from .geometry import transform_points

DEFAULTS = {
    "enabled": False,
    "kind": "image",          # image / text
    "text": "LEVEL7",
    "image_b64": "",          # the logo file itself (SVG / PNG / JPG / WebP), so the project opens anywhere
    "image_name": "",
    "position": "center",     # center / top / bottom / left / right
    "align": "grain",         # grain / long
    "size_pct": 50,
    "max_mm": 200.0,
    "opacity": 35,            # %
    "color": "original",      # original / dark / light
    "upright": True,          # copies turned 180 deg show it the right way up (else it turns with the piece)
    "excluded": [],           # piece uids without the watermark
}
POSITIONS = ("center", "top", "bottom", "left", "right")
MIN_MM = 8.0


def settings(project) -> dict:
    """The project's watermark settings with every key present."""
    d = dict(DEFAULTS)
    d.update(getattr(project, "watermark", None) or {})
    return d


def active(cfg: dict) -> bool:
    return bool(cfg.get("enabled")) and (bool(cfg.get("image_b64")) if cfg.get("kind") == "image"
                                         else bool((cfg.get("text") or "").strip()))


def _fits(inner, cx, cy, w, h) -> bool:
    return inner.contains(box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))


@lru_cache(maxsize=4096)
def _frame(cut: tuple, theta: float, position: str, size_pct: float, max_mm: float, aspect: float):
    poly = Polygon(cut).buffer(0)
    if poly.is_empty or poly.area <= 0:
        return None
    rp = affinity.rotate(poly, -theta, origin=(0, 0))          # logo frame: x = reading direction, y = up
    x0, y0, x1, y1 = rp.bounds
    pw, ph = x1 - x0, y1 - y0
    inner = rp.buffer(-max(1.5, 0.03 * min(pw, ph)))
    if inner.is_empty:
        return None
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    half = {"top": box(x0, my, x1, y1), "bottom": box(x0, y0, x1, my), "left": box(x0, y0, mx, y1),
            "right": box(mx, y0, x1, y1)}.get(position)
    region = inner.intersection(half) if half is not None else inner
    if region.is_empty:
        region = inner
    if region.geom_type != "Polygon":
        region = max(getattr(region, "geoms", [region]), key=lambda g: getattr(g, "area", 0.0))
        if region.geom_type != "Polygon" or region.area <= 0:
            return None
    c = polylabel(region, tolerance=max(0.5, 0.01 * min(pw, ph)))
    cx, cy = c.x, c.y
    w = min(size_pct / 100.0 * pw, max_mm)
    h = w / aspect
    if h > size_pct / 100.0 * ph:                            # a tall logo on a narrow piece: limited by the height
        h = size_pct / 100.0 * ph
        w = h * aspect
    while w >= MIN_MM and not _fits(inner, cx, cy, w, h):
        w *= 0.9
        h *= 0.9
    if w < MIN_MM:
        return None
    a = math.radians(theta)
    return cx * math.cos(a) - cy * math.sin(a), cx * math.sin(a) + cy * math.cos(a), w, h


def _theta(cut, grain_angle, align) -> float:
    if align == "long":
        r = Polygon(cut).buffer(0).minimum_rotated_rectangle
        pts = list(r.exterior.coords)[:4]
        e = max(((pts[i], pts[i + 1]) for i in range(3)), key=lambda e: math.dist(*e))
        a = math.degrees(math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0]))
    else:
        a = grain_angle or 0.0
    a = (a + 90.0) % 180.0 - 90.0                           # (-90, 90]: never upside down in the pattern
    return round(a, 3)


def piece_frame(piece, size: str, cfg: dict, aspect: float):
    """(cx, cy, theta deg, w, h) of the watermark in pattern coordinates of ``piece`` / ``size``, or None."""
    g = piece.sizes.get(size)
    if g is None or len(g.cut) < 3:
        return None
    theta = _theta(g.cut, piece.grain_angle, cfg.get("align", "grain"))
    f = _frame(tuple(map(tuple, g.cut)), theta, cfg.get("position", "center"), float(cfg.get("size_pct", 50)),
               float(cfg.get("max_mm", 150.0)), round(max(0.05, aspect), 4))
    if f is None:
        return None
    return f[0], f[1], theta, f[2], f[3]


def placement_corners(piece, pl, cfg: dict, aspect: float):
    """(top-left, top-right, bottom-left) of the watermark of one copy in marker coordinates, or None."""
    if not pl.placed or piece.uid in set(cfg.get("excluded") or ()):
        return None
    f = piece_frame(piece, pl.size, cfg, aspect)
    if f is None:
        return None
    cx, cy, theta, w, h = f
    a = math.radians(theta)
    u = (math.cos(a), math.sin(a))
    v = (-math.sin(a), math.cos(a))
    (c,) = transform_points([(cx, cy)], pl.rotation, pl.mirrored, pl.x, pl.y, pl.sx, pl.sy)
    (u,) = transform_points([u], pl.rotation, pl.mirrored, 0.0, 0.0, pl.sx, pl.sy)
    (v,) = transform_points([v], pl.rotation, pl.mirrored, 0.0, 0.0, pl.sx, pl.sy)
    if u[0] * v[1] - u[1] * v[0] < 0:                       # mirrored copy: keep the logo readable
        u = (-u[0], -u[1])
    if cfg.get("upright", True) and (u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0)):
        u, v = (-u[0], -u[1]), (-v[0], -v[1])               # copy turned 180 deg: the logo still reads upright
    tl = (c[0] - u[0] * w / 2 + v[0] * h / 2, c[1] - u[1] * w / 2 + v[1] * h / 2)
    tr = (tl[0] + u[0] * w, tl[1] + u[1] * w)
    bl = (tl[0] - v[0] * h, tl[1] - v[1] * h)
    return tl, tr, bl
