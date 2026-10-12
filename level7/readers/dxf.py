"""Generic DXF import (additional path; NOT a substitute for native GRAFIS reading).

Each closed polyline on a cut layer becomes a piece (one size, "base"). A LINE or
open polyline on a layer named like GRAIN lying inside a piece defines its grain.
AAMA/ASTM conventions are not interpreted. Units come from $INSUNITS.
"""
from __future__ import annotations

import os

import ezdxf
from shapely.geometry import LineString, Polygon

from ..geometry import grain_angle, ring_area
from ..model import CutOrder, Piece, PieceGeometry, Polyline, Project, SourceInfo, Status
from ..formats.grafis.container import sha256_bytes

UNIT_TO_MM = {0: None, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}


def read_dxf(path: str, cut_layers: tuple[str, ...] = ("CUT", "0", "1"), grain_layers=("GRAIN", "7")):
    issues: list[str] = []
    doc = ezdxf.readfile(path)
    ins = doc.header.get("$INSUNITS", 0)
    f = UNIT_TO_MM.get(ins)
    if f is None:
        f = 1.0
        issues.append(f"$INSUNITS={ins}: unit not declared, assuming millimetres - verify!")
    msp = doc.modelspace()
    closed, opens = [], []
    for e in msp.query("LWPOLYLINE POLYLINE LINE"):
        layer = e.dxf.layer.upper()
        if e.dxftype() == "LINE":
            pts = [(e.dxf.start.x * f, e.dxf.start.y * f), (e.dxf.end.x * f, e.dxf.end.y * f)]
            opens.append((layer, pts))
            continue
        pts = [(p[0] * f, p[1] * f) for p in (e.get_points("xy") if e.dxftype() == "LWPOLYLINE"
                                               else [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices])]
        is_closed = e.closed or (len(pts) > 2 and pts[0] == pts[-1])
        if is_closed and layer in [c.upper() for c in cut_layers]:
            if pts[0] == pts[-1]:
                pts = pts[:-1]
            closed.append(pts)
        else:
            opens.append((layer, pts))
    with open(path, "rb") as fh:
        sha = sha256_bytes(fh.read())
    proj = Project(name=os.path.splitext(os.path.basename(path))[0], size_names=["base"])
    proj.sources.append(SourceInfo(os.path.abspath(path), "dxf", sha, os.path.getsize(path),
                                   notes=["generic DXF import; not GRAFIS-native"]))
    for i, pts in enumerate(closed, 1):
        if ring_area(pts) < 0:
            pts = pts[::-1]
        g = PieceGeometry(size="base", cut=pts, source=f"DXF closed polyline #{i}", unit_factor=f,
                          source_unit={1.0: "mm", 10.0: "cm", 25.4: "inch", 304.8: "ft", 1000.0: "m"}.get(f, "?"))
        g.completeness = {"cut": Status.CONFIRMED.value, "grain": Status.UNKNOWN.value}
        poly = Polygon(pts)
        for layer, op in opens:
            if layer in [x.upper() for x in grain_layers] and poly.contains(LineString(op)):
                g.grain = Polyline(op)
                g.completeness["grain"] = Status.CONFIRMED.value
        piece = Piece(uid=Piece.new_uid(), source_id=f"dxf:{i}", number=i, name=f"piece {i}", sizes={"base": g})
        if g.grain:
            piece.grain_angle = grain_angle(g.grain.points)
        else:
            piece.notes.append("grain direction unknown - define it before nesting")
        proj.pieces.append(piece)
    proj.cut_order = CutOrder(size_quantities={"base": 1},
                              piece_counts={p.uid: (1, 0) for p in proj.pieces})
    if not closed:
        issues.append("no closed polylines found on cut layers " + ",".join(cut_layers))
    return proj, issues
