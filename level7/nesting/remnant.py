"""Remnant: after nesting, the small pieces are packed together so that the fabric left in the marker is one
large piece (owner of LEVEL7 MTM: "gather the small pieces next to each other when there are big gaps, so
the remaining area is large and in one piece").

The long pieces (those that make the marker length) stay where they are. The small pieces are taken out and
put back one by one, each where the largest empty rectangle of the marker stays largest (among the positions
where it touches other pieces or the fabric edge most). Only translations and the turns the piece is allowed
(grain) are used; the marker length never grows. The search runs on a raster of the fabric (conservative:
cells are counted as taken with a margin); the result is checked exactly by the validator. When it is not
valid, or the largest empty rectangle does not grow, nothing changes.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import shapely
from shapely.geometry import Polygon

from ..geometry import placement_points
from ..model import Marker, NestSettings, Project

CELL = 5.0            # mm: raster cell for the search
POOL = 2              # the largest free rectangle is measured on cells of POOL x CELL (faster)
CANDIDATES = 8        # positions tried per piece and turn (the best touching ones)
MIN_GAIN = 1.05       # keep the new layout only when the largest empty rectangle grows by 5 % or more


def largest_rect(free: np.ndarray) -> tuple[int, tuple[int, int, int, int]]:
    """Largest all-True axis-parallel rectangle in a 2-D bool array: (cells, (row0, col0, row1, col1))."""
    ny, nx = free.shape
    h = np.zeros(nx, dtype=np.int32)
    best, where = 0, (0, 0, 0, 0)
    for r in range(ny):
        h = np.where(free[r], h + 1, 0)
        stack = []
        for c in range(nx + 1):
            cur = int(h[c]) if c < nx else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, hh = stack.pop()
                area = hh * (c - s)
                if area > best:
                    best, where = area, (r - hh + 1, s, r + 1, c)
                start = s
            stack.append((start, cur))
    return best, where


def _pool(occ: np.ndarray) -> np.ndarray:
    """Coarser raster: a pooled cell is taken when any of its cells is."""
    ny, nx = occ.shape
    py, px = -(-ny // POOL) * POOL, -(-nx // POOL) * POOL
    pad = np.ones((py, px), dtype=bool)
    pad[:ny, :nx] = occ
    return pad.reshape(py // POOL, POOL, px // POOL, POOL).any(axis=(1, 3))


def _cells(poly, x0, y0, ny, nx):
    """Raster cells (row, col) whose centre lies in ``poly`` (a grown region) on the grid at (x0, y0)."""
    bx0, by0, bx1, by1 = poly.bounds
    c0, c1 = max(0, int(math.floor((bx0 - x0) / CELL))), min(nx, int(math.ceil((bx1 - x0) / CELL)) + 1)
    r0, r1 = max(0, int(math.floor((by0 - y0) / CELL))), min(ny, int(math.ceil((by1 - y0) / CELL)) + 1)
    if c1 <= c0 or r1 <= r0:
        return None
    cx = x0 + (np.arange(c0, c1) + 0.5) * CELL
    cy = y0 + (np.arange(r0, r1) + 0.5) * CELL
    X, Y = np.meshgrid(cx, cy)
    inside = shapely.contains_xy(poly, X, Y)
    return r0, c0, inside


def _mask(poly):
    """The piece as a raster mask with its own origin at the grown polygon's lower bounds."""
    bx0, by0, bx1, by1 = poly.bounds
    w, h = max(1, int(math.ceil((bx1 - bx0) / CELL))), max(1, int(math.ceil((by1 - by0) / CELL)))
    cx = bx0 + (np.arange(w) + 0.5) * CELL
    cy = by0 + (np.arange(h) + 0.5) * CELL
    X, Y = np.meshgrid(cx, cy)
    return shapely.contains_xy(poly, X, Y), bx0, by0


def _corr(a: np.ndarray, k: np.ndarray) -> np.ndarray:
    """sum a[r+i, c+j] * k[i, j] for every (r, c) where k fits in a (FFT)."""
    ny, nx = a.shape
    h, w = k.shape
    if h > ny or w > nx:
        return np.zeros((0, 0))
    kp = np.zeros((ny, nx))
    kp[:h, :w] = k
    out = np.fft.irfft2(np.fft.rfft2(a.astype(float)) * np.conj(np.fft.rfft2(kp)), s=(ny, nx))
    return out[: ny - h + 1, : nx - w + 1]


def _best_place(pl, piece, st, occ, grow):
    """The position (and allowed turn) of this piece that leaves the largest free rectangle, or None."""
    from .engine import grain_rotations
    rots, _ = grain_rotations(piece, pl.mirrored, st)
    rots = list(dict.fromkeys([pl.rotation] + list(rots or [])))[:4]
    g = piece.sizes[pl.size]
    best = None
    for rot in rots:
        poly = Polygon(placement_points(g.cut, replace(pl, x=0.0, y=0.0, rotation=rot)))
        m, bx0, by0 = _mask(poly.buffer(grow))
        h, w = m.shape
        hit = _corr(occ, m)
        if hit.size == 0:
            continue
        free = hit < 0.5
        if not free.any():
            continue
        ring = np.zeros((h + 2, w + 2), dtype=bool)
        for di in range(3):
            for dj in range(3):
                ring[di:di + h, dj:dj + w] |= m
        ring[1:1 + h, 1:1 + w] &= ~m
        touch = _corr(np.pad(occ, 1, constant_values=True), ring)[: free.shape[0], : free.shape[1]]
        score = np.where(free, touch, -1.0)
        for idx in np.argsort(score, axis=None)[::-1][:CANDIDATES]:
            r, c = divmod(int(idx), score.shape[1])
            if score[r, c] < 0:
                break
            trial = occ.copy()
            trial[r:r + h, c:c + w] |= m
            area, _ = largest_rect(~_pool(trial))
            key = (area, score[r, c], -c)
            if best is None or key > best[0]:
                best = (key, rot, r, c, m, bx0, by0)
    return best


def consolidate(proj: Project, marker: Marker, settings: NestSettings | None = None,
                validate=None) -> tuple[Marker | None, dict]:
    """A copy of ``marker`` with the small pieces packed together, or None (no gain / not possible)."""
    from ..validation.checker import placed_polygons
    f = marker.fabric
    info = {"done": False}
    if f.buffer_x > 0 or f.buffer_y > 0 or f.repeat_x > 0 or f.repeat_y > 0:
        info["why"] = "buffers / pattern matching: not changed"
        return None, info
    polys = placed_polygons(proj, marker)
    placed = [pl for pl in marker.placements if pl.placed and pl.uid in polys]
    if len(placed) < 3:
        return None, info
    x0, y0 = f.margin_start, f.margin_left
    x1 = max(polys[pl.uid].bounds[2] for pl in placed)             # never longer than now
    y1 = f.margin_left + f.usable_width
    nx, ny = int(math.ceil((x1 - x0) / CELL)), int(math.ceil((y1 - y0) / CELL))
    if nx < 2 or ny < 2:
        return None, info
    length = x1 - x0
    big_area = max(polys[pl.uid].area for pl in placed)

    fixed: set[str] = set()                       # small pieces that found no other place: they stay

    def is_big(pl):
        b = polys[pl.uid].bounds
        return (pl.pinned or pl.uid in fixed or (b[2] - b[0]) >= 0.45 * length
                or polys[pl.uid].area >= 0.3 * big_area)
    grow = f.spacing / 2 + CELL * 0.71             # every cell a piece (+ half the spacing) touches is taken

    def blank():
        occ = np.zeros((ny, nx), dtype=bool)
        if y0 + ny * CELL > y1 + 1e-6:                             # cells reaching past the fabric edge
            occ[-1, :] = True
        if x0 + nx * CELL > x1 + 1e-6:
            occ[:, -1] = True
        return occ

    def stamp(occ, poly):
        got = _cells(poly.buffer(grow), x0, y0, ny, nx)
        if got:
            r0, c0, inside = got
            occ[r0:r0 + inside.shape[0], c0:c0 + inside.shape[1]] |= inside

    before = blank()
    for pl in placed:
        stamp(before, polys[pl.uid])
    rect0, _ = largest_rect(~_pool(before))
    pieces = {p.uid: p for p in proj.pieces}
    st = settings or NestSettings()
    for _attempt in range(6):
        small = sorted((pl for pl in placed if not is_big(pl)), key=lambda pl: -polys[pl.uid].area)
        if not small:
            return None, info
        occ = blank()
        for pl in placed:
            if is_big(pl):
                stamp(occ, polys[pl.uid])
        new, stuck = {}, None
        for pl in small:
            best = _best_place(pl, pieces[pl.piece_uid], st, occ, grow)
            if best is None:
                stuck = pl.uid
                break
            _, rot, r, c, m, bx0, by0 = best
            occ[r:r + m.shape[0], c:c + m.shape[1]] |= m
            new[pl.uid] = replace(pl, rotation=rot, x=x0 + c * CELL - bx0, y=y0 + r * CELL - by0)
        if stuck is None:
            break
        fixed.add(stuck)                            # keep it where it was and arrange the others around it
    else:
        info["why"] = "no arrangement found"
        return None, info
    rect1, _ = largest_rect(~_pool(occ))
    cm2 = (CELL * POOL) ** 2 / 1e6
    info.update(before_m2=round(rect0 * cm2, 3), after_m2=round(rect1 * cm2, 3))
    if rect1 < rect0 * MIN_GAIN:
        info["why"] = "largest free piece not larger"
        return None, info
    out = replace(marker, placements=[new.get(pl.uid, pl) for pl in marker.placements])
    if validate is not None and not validate(out):
        info["why"] = "the packed layout did not pass the check"
        return None, info
    info["done"] = True
    return out, info
