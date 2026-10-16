"""HP-GL / PLT import: a marker plotted to a file (GRAFIS, Gerber, Lectra ... plotter output).

A PLT holds only pen strokes, no piece data, so the marker is rebuilt from the drawing:

* PU / PD / PA / PR (absolute and relative), IN, SP and LB (text, skipped) are read; 40 plotter units = 1 mm.
* Strokes are chained end to start (a piece outline is often drawn in several strokes) into closed contours.
* Every closed contour that is not inside a larger one is a piece; contours and strokes inside a piece are its
  inner lines. Notch slits drawn as out-and-back spikes become notches.
* Pieces of the same shape (also turned 180 deg or mirrored) become one part with several placements, so the
  marker can be checked, re-nested and exported. Parts are named "PLT 01" ... in drawing order.
* The size of every piece is read from the text plotted inside it (GRAFIS draws it with a single-stroke font; HP-GL
  LB labels are read too); pieces of the same shape but another size are separate parts.
* Not in a PLT, so set by hand: part names, materials and the fabric width (from the file name "..._1480.plt" or
  estimated from the drawing). The grain is assumed along the marker length as plotted.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon

from ..formats.grafis.container import sha256_bytes
from ..geometry import bbox, ring_area, transform_points
from ..model import (CutOrder, FabricSettings, Marker, Notch, Piece, PieceGeometry, Placement, Polyline, Project,
                     SourceInfo, Status)
from .dxf import strip_spikes
from .plt_text import ambiguous, candidates, choose, clusters, is_glyph_stroke

UNITS_PER_MM = 40.0
JOIN_TOL = 0.5            # mm: stroke ends closer than this are joined
MIN_AREA = 200.0          # mm2: smaller closed contours are marks, not pieces
SIZE = "PLT"
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")


class PltError(ValueError):
    pass


def read_strokes(data: bytes, labels: list | None = None) -> list[list[tuple[float, float]]]:
    """Pen-down polylines (mm) of an HP-GL file; LB texts go to ``labels`` as (position mm, text)."""
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
            if labels is not None and text[i:n if j < 0 else j].strip():
                labels.append((pos, text[i:n if j < 0 else j].strip()))
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
    """Join strokes end to end; returns (closed contours without the repeated end point, open polylines).
    Stroke ends are found through a grid of ``tol`` cells (thousands of strokes in a big marker)."""
    pool = {i: list(st) for i, st in enumerate(strokes)}
    grid: dict = {}

    def cell(p):
        return int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol))

    for i, st in pool.items():
        for e in (0, -1):
            grid.setdefault(cell(st[e]), []).append(i)

    def near(p, skip):
        cx, cy = cell(p)
        best = None
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for j in grid.get((gx, gy), ()):
                    if j != skip and j in pool and (best is None or j < best):
                        o = pool[j]
                        if math.dist(p, o[0]) <= tol or math.dist(p, o[-1]) <= tol:
                            best = j
        return best

    closed, opens = [], []
    for i in sorted(pool):
        if i not in pool:
            continue
        c = pool.pop(i)
        while math.dist(c[0], c[-1]) > tol:
            j = near(c[-1], i)
            if j is not None:
                o = pool.pop(j)
                c = c + (o[1:] if math.dist(c[-1], o[0]) <= tol else o[::-1][1:])
                continue
            j = near(c[0], i)
            if j is not None:
                o = pool.pop(j)
                c = (o[:-1] if math.dist(c[0], o[-1]) <= tol else o[::-1][:-1]) + c
                continue
            break
        if len(c) > 3 and math.dist(c[0], c[-1]) <= tol:
            closed.append(c[:-1])
        else:
            opens.append(c)
    return closed, opens


def _plausible(t: str) -> bool:
    """A text, not a lone mark: short lines and slashes alone read as "-", "/", "1", "I" ..."""
    return any(c not in "-/.()+1IL7V " for c in t)


def _size_name(t: str) -> str:
    return t.strip().replace(":", "-") or SIZE


def _size_sort(s: str):
    try:
        return (0, float(s), s)
    except ValueError:
        return (1, 0.0, s)


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
    lb: list = []
    strokes = read_strokes(data, lb)
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
    grown = [s[3].buffer(0.5) for s in shapes]
    tree = STRtree(grown)
    pieces_, inner = [], []
    for i, s in enumerate(shapes):
        if any(j < i and grown[j].contains(s[3]) for j in tree.query(s[3])):
            inner.append(s[0] + s[0][:1])
        else:
            pieces_.append(s)
    if not pieces_:
        raise PltError("no closed piece outlines found in this PLT / HP-GL file")
    pieces_.sort(key=lambda s: (round(s[3].bounds[0], 1), round(s[3].bounds[1], 1)))   # drawing order along x
    with_inner = opens + inner
    ptree = STRtree([s[3] for s in pieces_])

    def piece_at(pt):
        hits = [int(i) for i in ptree.query(pt, predicate="intersects")]
        return min(hits) if hits else None
    # texts plotted inside the pieces (GRAFIS: the size, drawn with a single-stroke font) and HP-GL labels
    texts: dict[int, list] = {}                          # piece index -> [(text, strokes)]
    glyphs = [o for o in opens if is_glyph_stroke(o)]
    found_ = []                                          # (piece index, strokes, readings)
    for cl in clusters(glyphs):
        c = Point(sum(p[0] for s in cl for p in s) / sum(len(s) for s in cl),
                  sum(p[1] for s in cl for p in s) / sum(len(s) for s in cl))
        k = piece_at(c)
        if k is not None:
            found_.append((k, cl, candidates(cl)))
    # a text that also reads turned 180 deg (6 / 9) takes the direction of the clear texts of its piece, else of
    # most clear texts of the marker
    clear = [(k, cs[0][1]) for k, _, cs in found_ if cs and not ambiguous(cs)]
    overall = [r for r, _ in Counter(r for _, r in clear).most_common()]
    for k, cl, cs in found_:
        own = [r for r, _ in Counter(r for kk, r in clear if kk == k).most_common()]
        t, _ = choose(cs, own + overall)
        if t and _plausible(t):
            texts.setdefault(k, []).append((t, cl))
    for pos, t in lb:
        k = piece_at(Point(pos))
        if k is not None:
            texts.setdefault(k, []).append((t, []))
    for v in texts.values():                              # "FRONT 44": the size is the last word
        for i, (t, cl) in enumerate(list(v)):
            words = [w for w in t.split() if not (w.startswith("(") and w.endswith(")"))]   # "(M)" = mirrored
            if len(words) == 1:
                v[i] = (words[0], cl)
            elif len(words) > 1:
                v[i] = (words[-1], cl)
                v.append((" ".join(words[:-1]), []))
    used = {id(st) for v in texts.values() for _, cl in v for st in cl}
    with_inner = [o for o in with_inner if id(o) not in used and len(o) > 1]   # read texts are not inner lines
    ltree = STRtree([LineString(o) for o in with_inner])
    proj = Project(name=os.path.splitext(os.path.basename(path))[0], size_names=[])
    proj.sources.append(SourceInfo(os.path.abspath(path), "plt", sha256_bytes(data), len(data),
                                   notes=["HP-GL / PLT import: pieces rebuilt from the plotted outlines"]))
    read = {_size_name(sorted(v, key=lambda t: (len(t[0]), t[0]))[0][0]) for v in texts.values()}
    only = next(iter(read)) if len(read) == 1 else None      # one size in the marker: small parts without text too
    groups: list[tuple[Piece, list, Polygon, str]] = []  # (part, canonical cut, its polygon, size)
    placements = []
    unread = 0
    for idx, (raw, pts, spikes, poly) in enumerate(pieces_):
        found = sorted(texts.get(idx, []), key=lambda t: (len(t[0]), t[0]))
        size = _size_name(found[0][0]) if found else (only or SIZE)
        unread += not found and only is None
        extra = " ".join(dict.fromkeys(w for t, _ in found[1:] for w in t.split()
                                       if w != size and w.strip("?")))     # other texts, once, without the size
        hit = None
        for part, cut, cpoly, gsize in groups:
            if gsize != size:
                continue
            m = _match(cut, cpoly, poly)
            if m is not None:
                hit = (part, m)
                break
        if hit is None:
            x0, y0 = poly.bounds[0], poly.bounds[1]
            cut = [(x - x0, y - y0) for x, y in pts]
            k = len(groups) + 1
            g = PieceGeometry(size=size, cut=cut, source=f"PLT outline #{k}", source_unit="plotter unit",
                              unit_factor=1.0 / UNITS_PER_MM)
            g.completeness = {"cut": Status.CONFIRMED.value, "grain": Status.PROBABLE.value,
                              "notches": Status.PROBABLE.value if spikes else Status.UNKNOWN.value}
            for base, tip in spikes:
                ln = math.dist(base, tip)
                g.notches.append(Notch((base[0] - x0, base[1] - y0),
                                       ((tip[0] - base[0]) / ln, (tip[1] - base[1]) / ln), ln))
            area = poly.buffer(0.5)
            for j in sorted(int(j) for j in ltree.query(area, predicate="contains")):
                g.internal.append(Polyline([(x - x0, y - y0) for x, y in with_inner[j]]))
            part = Piece(uid=Piece.new_uid(), source_id=f"plt:{k}", number=k,
                         name=f"PLT {k:02d}" + (f" {extra}" if extra else ""), sizes={size: g}, grain_angle=0.0,
                         notes=["from a PLT: name, material and grain direction are not in the file - check them"])
            cpoly = Polygon(cut).buffer(0)
            groups.append((part, cut, cpoly, size))
            hit = (part, (0.0, False, x0, y0))
        part, (rot, mir, dx, dy) = hit
        if mir:
            part.allow_mirror = True
        placements.append(Placement(uid=Piece.new_uid(), piece_uid=part.uid, size=size, x=dx, y=dy,
                                    rotation=rot, mirrored=mir))
    proj.pieces = [g[0] for g in groups]
    counts = {}
    for pl in placements:
        n, m = counts.get(pl.piece_uid, (0, 0))
        counts[pl.piece_uid] = (n, m + 1) if pl.mirrored else (n + 1, m)
    for p in proj.pieces:
        p.default_count, p.default_mirrored = counts[p.uid]
    proj.size_names = sorted({pl.size for pl in placements}, key=_size_sort)
    proj.cut_order = CutOrder(size_quantities={sz: 1 for sz in proj.size_names}, piece_counts=dict(counts))
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
    issues.append(f"PLT: {len(placements)} pieces drawn, {len(proj.pieces)} different shapes, sizes "
                  f"{', '.join(s for s in proj.size_names if s != SIZE) or '-'} read from the texts in the pieces; "
                  f"part names and materials are not in a PLT")
    if unread:
        issues.append(f"{unread} pieces without a readable size text: size \"{SIZE}\" - check them")
    return proj, issues
