"""Generic DXF import (additional path; NOT a substitute for native GRAFIS reading).

* Block references (INSERT) are exploded, so piece-per-block files (e.g. GRAFIS DXF export) work.
* Each closed polyline on a cut layer becomes a piece (size "base"). Notch slits embedded in the
  contour as there-and-back spikes (GRAFIS layer 1 convention) are removed from the contour and
  kept as notches.
* Open polylines/lines on seam layers become seam lines; lines on grain layers inside a piece define
  its grain. Without a grain layer the grain is UNKNOWN and must be set before nesting.
* AAMA/ASTM conventions are not interpreted. Units come from $INSUNITS (missing = assumed mm, warned).
"""
from __future__ import annotations

import math
import os

import ezdxf
from shapely.geometry import LineString, Polygon

from ..formats.grafis.container import sha256_bytes
from ..geometry import grain_angle, ring_area
from ..model import CutOrder, Notch, Piece, PieceGeometry, Polyline, Project, SourceInfo, Status

UNIT_TO_MM = {0: None, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}
CUT_LAYERS = ("CUT", "1", "0")        # "1" = GRAFIS / AAMA-style boundary layer
SEAM_LAYERS = ("SEAM", "8")           # "8" = seam layer in GRAFIS DXF export
GRAIN_LAYERS = ("GRAIN",)


def strip_spikes(pts, tol=1e-3):
    """Remove A-B-A spikes from a closed vertex list; returns (contour, [(base, tip), ...])."""
    out, spikes = list(pts), []
    changed = True
    while changed:
        changed = False
        n = len(out)
        for i in range(n):
            a, b, c = out[i - 1], out[i], out[(i + 1) % n]
            if n > 4 and math.dist(a, c) < tol and math.dist(a, b) > tol:
                spikes.append((a, b))
                for k in sorted({i, (i + 1) % n}, reverse=True):
                    del out[k]
                changed = True
                break
    return out, spikes


def _entities(msp, depth=0):
    for e in msp:
        if e.dxftype() == "INSERT":
            if depth < 8:                  # blocks inside blocks too (a guard against self-referencing blocks)
                yield from _entities(e.virtual_entities(), depth + 1)
        else:
            yield e


def read_dxf(path: str, cut_layers=CUT_LAYERS, seam_layers=SEAM_LAYERS, grain_layers=GRAIN_LAYERS):
    issues: list[str] = []
    doc = ezdxf.readfile(path)
    ins = doc.header.get("$INSUNITS", 0)
    f = UNIT_TO_MM.get(ins)
    if f is None:
        f = 1.0
        issues.append(f"$INSUNITS={ins}: unit not declared, assuming millimetres - verify!")
    cut_l = {c.upper() for c in cut_layers}
    seam_l = {c.upper() for c in seam_layers}
    grain_l = {c.upper() for c in grain_layers}
    closed, opens = [], []
    skipped = 0
    for e in _entities(doc.modelspace()):
        layer = e.dxf.layer.upper()
        t = e.dxftype()
        if t == "LINE":
            pts = [(e.dxf.start.x * f, e.dxf.start.y * f), (e.dxf.end.x * f, e.dxf.end.y * f)]
            opens.append((layer, pts))
            continue
        if t == "LWPOLYLINE":
            pts = [(p[0] * f, p[1] * f) for p in e.get_points("xy")]
        elif t == "POLYLINE":
            pts = [(v.dxf.location.x * f, v.dxf.location.y * f) for v in e.vertices]
        else:
            continue
        is_closed = e.is_closed or (len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6)
        if is_closed and layer in cut_l:
            if math.dist(pts[0], pts[-1]) < 1e-6:
                pts = pts[:-1]
            if len(pts) < 3 or abs(ring_area(pts)) < 1e-6:
                skipped += 1                # a stray closed line with no area: not a piece
                continue
            closed.append(pts)
        elif len(pts) >= 2:
            opens.append((layer, pts))
        else:
            skipped += 1
    with open(path, "rb") as fh:
        sha = sha256_bytes(fh.read())
    proj = Project(name=os.path.splitext(os.path.basename(path))[0], size_names=["base"])
    proj.sources.append(SourceInfo(os.path.abspath(path), "dxf", sha, os.path.getsize(path),
                                   notes=["generic DXF import; not GRAFIS-native"]))
    for i, raw in enumerate(closed, 1):
        pts, spikes = strip_spikes(raw)
        if ring_area(pts) < 0:
            pts = pts[::-1]
        g = PieceGeometry(size="base", cut=pts, source=f"DXF closed polyline #{i}", unit_factor=f,
                          source_unit={1.0: "mm", 10.0: "cm", 25.4: "inch", 304.8: "ft", 1000.0: "m"}.get(f, "?"))
        g.completeness = {"cut": Status.CONFIRMED.value, "grain": Status.UNKNOWN.value,
                          "notches": Status.PROBABLE.value if spikes else Status.UNKNOWN.value}
        for base, tip in spikes:
            ln = math.dist(base, tip)
            g.notches.append(Notch(base, ((tip[0] - base[0]) / ln, (tip[1] - base[1]) / ln), ln))
        poly = Polygon(pts).buffer(0.01)
        for layer, op in opens:
            if not poly.contains(LineString(op)):
                continue
            if layer in grain_l:
                g.grain = Polyline(op)
                g.completeness["grain"] = Status.CONFIRMED.value
            elif layer in seam_l:
                g.seam.append(Polyline(op))
            else:
                g.internal.append(Polyline(op))
        piece = Piece(uid=Piece.new_uid(), source_id=f"dxf:{i}", number=i, name=f"piece {i}", sizes={"base": g})
        if g.grain:
            piece.grain_angle = grain_angle(g.grain.points)
        else:
            piece.notes.append("grain direction unknown - define it before nesting")
        proj.pieces.append(piece)
    proj.cut_order = CutOrder(size_quantities={"base": 1}, piece_counts={p.uid: (1, 0) for p in proj.pieces})
    if skipped:
        issues.append(f"{skipped} degenerate polylines (fewer than 3 points / no area) were skipped")
    if not closed:
        issues.append("no closed polylines found on cut layers " + ",".join(cut_layers))
    elif not any(p.grain_angle is not None for p in proj.pieces):
        issues.append("no grain lines found: grain direction must be defined per piece before nesting")
    return proj, issues
