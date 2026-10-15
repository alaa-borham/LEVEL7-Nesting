"""HP-GL / PLT import: a marker plotted to a file (GRAFIS, Gerber, Lectra ... plotter output).

A PLT holds only pen strokes, no piece data, so the marker is rebuilt from the drawing:

* PU / PD / PA / PR (absolute and relative), IN, SP and LB (text, skipped) are read; 40 plotter units = 1 mm.
* Strokes are chained end to start (a piece outline is often drawn in several strokes) into closed contours.
* Every closed contour that is not inside a larger one is a piece; contours and strokes inside a piece are its
  inner lines. Notch slits drawn as out-and-back spikes become notches.
* Pieces of the same shape (also turned 180 deg or mirrored) become one part with several placements, so the
  marker can be checked, re-nested and exported. Parts are named "PLT 01" ... in drawing order.
* Not in a PLT, so set by hand: part names, sizes, materials and the fabric width (estimated from the drawing).
  The grain is assumed along the marker length as plotted.
"""
from __future__ import annotations

import math
import os
import re

from shapely.geometry import LineString, Polygon

from ..formats.grafis.container import sha256_bytes
from ..geometry import bbox, ring_area, transform_points
from ..model import (CutOrder, FabricSettings, Marker, Notch, Piece, PieceGeometry, Placement, Polyline, Project,
                     SourceInfo, Status)
from .dxf import strip_spikes

UNITS_PER_MM = 40.0
JOIN_TOL = 0.5            # mm: stroke ends closer than this are joined
MIN_AREA = 200.0          # mm2: smaller closed contours are marks, not pieces
SIZE = "PLT"
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")


class PltError(ValueError):
    pass


def read_strokes(data: bytes) -> list[list[tuple[float, float]]]:
    """Pen-down polylines (mm) of an HP-GL file."""
    text = data.decode("latin-1")
    strokes: list[list[tuple[float, float]]] = []
    pos, pen, relative, cur = (0.0, 0.0), False, False, None
    term = "\x03"
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if not c.isalpha():
            i += 1
            continue
        m = text[i:i + 2].upper()
        i += 2
        if m == "LB":                                   # label text up to the terminator
            j = text.find(term, i)
            i = n if j < 0 else j + 1
            continue
        if m == "DT":                                   # label terminator
            if i < n and text[i] not in ";\r\n":
                term = text[i]
            j = text.find(";", i)
            i = n if j < 0 else j + 1
            continue
        if m.startswith("\x1b") or not m.isalpha():
            continue
        j = i
        while j < n and not text[j].isalpha() and text[j] != "\x1b":
            j += 1
        nums = [float(v) for v in _NUM.findall(text[i:j])]
        i = j
        pts = [(x / UNITS_PER_MM, y / UNITS_PER_MM) for x, y in zip(nums[0::2], nums[1::2])]
        if m in ("PU", "PD", "PA", "PR"):
            if m == "PA":
                relative = False
            elif m == "PR":
                relative = True
            if m == "PU":
                pen, cur = False, None
            elif m == "PD":
                pen = True
            for p in pts:
                p = (pos[0] + p[0], pos[1] + p[1]) if relative else p
                if pen:
                    if cur is None:
                        cur = [pos]
                        strokes.append(cur)
                    cur.append(p)
                pos = p
            if m == "PD" and not pts and cur is None:
                cur = [pos]
                strokes.append(cur)
        elif m == "IN":
            pos, pen, relative, cur = (0.0, 0.0), False, False, None
        elif m == "SP":
            cur = None
    return [s for s in strokes if len(s) > 1]


def chain(strokes, tol=JOIN_TOL):
    """Join strokes end to end; returns (closed contours without the repeated end point, open polylines)."""
    pool = [list(s) for s in strokes]
    closed, opens = [], []
    while pool:
        c = pool.pop(0)
        grown = True
        while grown and math.dist(c[0], c[-1]) > tol:
            grown = False
            for k, o in enumerate(pool):
                if math.dist(c[-1], o[0]) <= tol:
                    c = c + o[1:]
                elif math.dist(c[-1], o[-1]) <= tol:
                    c = c + o[::-1][1:]
                elif math.dist(c[0], o[-1]) <= tol:
                    c = o[:-1] + c
                elif math.dist(c[0], o[0]) <= tol:
                    c = o[::-1][:-1] + c
                else:
                    continue
                pool.pop(k)
                grown = True
                break
        if len(c) > 3 and math.dist(c[0], c[-1]) <= tol:
            closed.append(c[:-1])
        else:
            opens.append(c)
    return closed, opens


_ORIENT = ((0.0, False), (180.0, False), (0.0, True), (180.0, True))


def _match(rep_cut, rep_poly, shape_poly):
    """(rotation, mirrored, dx, dy) placing ``rep_cut`` onto ``shape_poly`` or None."""
    a = rep_poly.area
    if abs(shape_poly.area - a) > 0.005 * a:
        return None
    sb = shape_poly.bounds
    for rot, mir in _ORIENT:
        t = transform_points(rep_cut, rot, mir)
        b = bbox(t)
        if abs((b[2] - b[0]) - (sb[2] - sb[0])) > 1.0 or abs((b[3] - b[1]) - (sb[3] - sb[1])) > 1.0:
            continue
        dx, dy = sb[0] - b[0], sb[1] - b[1]
        moved = Polygon([(x + dx, y + dy) for x, y in t]).buffer(0)
        if moved.symmetric_difference(shape_poly).area < 0.005 * a:
            return rot, mir, dx, dy
    return None


def read_plt(path: str):
    issues: list[str] = []
    with open(path, "rb") as fh:
        data = fh.read()
    strokes = read_strokes(data)
    if not strokes:
        raise PltError("no drawing (pen-down strokes) in this PLT / HP-GL file")
    closed, opens = chain(strokes)
    shapes = []                                          # (raw contour, cleaned contour, spikes, polygon)
    for raw in closed:
        pts, spikes = strip_spikes(raw, tol=0.05)
        if len(pts) < 3:
            continue
        poly = Polygon(pts).buffer(0)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        if poly.is_empty or poly.area < MIN_AREA:
            if not poly.is_empty:
                opens.append(raw + raw[:1])
            continue
        if ring_area(pts) < 0:
            pts = pts[::-1]
        shapes.append((raw, pts, spikes, poly))
    # contours inside a larger one are inner lines of that piece
    shapes.sort(key=lambda s: -s[3].area)
    pieces_, inner = [], []
    for s in shapes:
        host = next((h for h in pieces_ if h[3].buffer(0.5).contains(s[3])), None)
        if host is None:
            pieces_.append(s)
        else:
            inner.append(s[0] + s[0][:1])
    if not pieces_:
        raise PltError("no closed piece outlines found in this PLT / HP-GL file")
    pieces_.sort(key=lambda s: (round(s[3].bounds[0], 1), round(s[3].bounds[1], 1)))   # drawing order along x
    with_inner = opens + inner
    proj = Project(name=os.path.splitext(os.path.basename(path))[0], size_names=[SIZE])
    proj.sources.append(SourceInfo(os.path.abspath(path), "plt", sha256_bytes(data), len(data),
                                   notes=["HP-GL / PLT import: pieces rebuilt from the plotted outlines"]))
    groups: list[tuple[Piece, list, Polygon]] = []       # (part, canonical cut, its polygon)
    placements = []
    for raw, pts, spikes, poly in pieces_:
        hit = None
        for part, cut, cpoly in groups:
            m = _match(cut, cpoly, poly)
            if m is not None:
                hit = (part, m)
                break
        if hit is None:
            x0, y0 = poly.bounds[0], poly.bounds[1]
            cut = [(x - x0, y - y0) for x, y in pts]
            k = len(groups) + 1
            g = PieceGeometry(size=SIZE, cut=cut, source=f"PLT outline #{k}", source_unit="plotter unit",
                              unit_factor=1.0 / UNITS_PER_MM)
            g.completeness = {"cut": Status.CONFIRMED.value, "grain": Status.PROBABLE.value,
                              "notches": Status.PROBABLE.value if spikes else Status.UNKNOWN.value}
            for base, tip in spikes:
                ln = math.dist(base, tip)
                g.notches.append(Notch((base[0] - x0, base[1] - y0),
                                       ((tip[0] - base[0]) / ln, (tip[1] - base[1]) / ln), ln))
            area = poly.buffer(0.5)
            for op in with_inner:
                if len(op) > 1 and area.contains(LineString(op)):
                    g.internal.append(Polyline([(x - x0, y - y0) for x, y in op]))
            part = Piece(uid=Piece.new_uid(), source_id=f"plt:{k}", number=k, name=f"PLT {k:02d}",
                         sizes={SIZE: g}, grain_angle=0.0,
                         notes=["from a PLT: name, material and grain direction are not in the file - check them"])
            cpoly = Polygon(cut).buffer(0)
            groups.append((part, cut, cpoly))
            hit = (part, (0.0, False, x0, y0))
        part, (rot, mir, dx, dy) = hit
        if mir:
            part.allow_mirror = True
        placements.append(Placement(uid=Piece.new_uid(), piece_uid=part.uid, size=SIZE, x=dx, y=dy,
                                    rotation=rot, mirrored=mir))
    proj.pieces = [g[0] for g in groups]
    counts = {}
    for pl in placements:
        n, m = counts.get(pl.piece_uid, (0, 0))
        counts[pl.piece_uid] = (n, m + 1) if pl.mirrored else (n + 1, m)
    for p in proj.pieces:
        p.default_count, p.default_mirrored = counts[p.uid]
    proj.cut_order = CutOrder(size_quantities={SIZE: 1}, piece_counts=dict(counts))
    allb = [s[3].bounds for s in pieces_]
    x0, y0 = min(b[0] for b in allb), min(b[1] for b in allb)
    if x0 < -0.5 or y0 < -0.5 or x0 > 50 or y0 > 50:      # drawing not at the plotter origin: move it to 0,0
        for pl in placements:
            pl.x -= x0
            pl.y -= y0
        allb = [(b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0) for b in allb]
    length = max(b[2] for b in allb)
    top = max(b[3] for b in allb)
    width = float(math.ceil(top / 10.0) * 10)            # estimated: the plot does not hold the fabric width
    m = re.search(r"(?<!\d)(\d{3,4})(?!\d)\s*$", proj.name)
    if m and top - 0.5 <= float(m.group(1)) <= top + 100:
        width = float(m.group(1))                         # "...-1500.plt": width in the file name
    else:
        issues.append(f"fabric width estimated from the drawing ({width:.0f} mm) - set the real width")
    marker = Marker(name=proj.name, fabric=FabricSettings(width=width), placements=placements, length=length,
                    origin="original")
    proj.markers.append(marker)
    issues.append(f"PLT: {len(placements)} pieces drawn, {len(proj.pieces)} different shapes; names, sizes and "
                  f"materials are not in a PLT")
    if opens and not any(p.sizes[SIZE].internal for p in proj.pieces):
        issues.append(f"{len(opens)} open strokes outside the pieces were ignored")
    return proj, issues
