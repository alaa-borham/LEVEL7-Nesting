"""Readers for GRAFIS MDL (pattern) and SCB (marker) files.

Both files share the same container and part/geometry blocks; SCB adds marker
sections (#SBINFO, #SBGRLST, #SBTLIST) and the placement block (2,8,0,0).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from ..formats.grafis.container import Container, read_container
from ..formats.grafis.contour import _simple as _simple_ring, chain_elements, outer_cycle
from ..formats.grafis.elements import KIND_POLYLINE, KIND_SYMBOL, KIND_TEXT, decode_geometry, symbol_position, text_anchor, text_angle
from ..formats.grafis.placements import decode_marker
from ..formats.grafis.textsections import DEFAULT_ENCODING, TextSections, parse_text
from ..geometry import bbox, grain_angle, ring_area, transform_points
from ..model import (CutOrder, Drill, FabricSettings, Label, Marker, Notch, Piece, PieceGeometry, Placement,
                     Polyline, Project, SourceInfo, Status)


NOTCH_ON_CUT_TOL = 0.01  # mm


@dataclass
class ReadResult:
    project: Project
    container: Container
    text: TextSections
    issues: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)


def _size_names(ts: TextSections) -> dict[int, str]:
    return {s.index: s.name for s in ts.sizes}


def _build_piece_geometry(payload: bytes, size_name: str, src: str, issues: list[str],
                          hint: dict | None = None) -> PieceGeometry | None:
    gb = decode_geometry(payload)
    for e in gb.errors:
        issues.append(f"{src}: {e}")
    polys = [e for e in gb.elements if e.kind == KIND_POLYLINE and len(e.points) >= 2]
    if not polys:
        return None
    flagged_cut = [e for e in polys if e.style == 0]
    contour = None
    cut_status = Status.PROBABLE.value
    cut_source = "outer element cycle"
    if flagged_cut:
        contour = chain_elements([(e.oid, e.points) for e in flagged_cut])
        if contour is not None:
            cut_status, cut_source = Status.CONFIRMED.value, "GRAFIS cut flag (style 0)"
        else:
            issues.append(f"{src}: style-0 cut elements do not close; falling back to outer cycle")
    if contour is None:
        cand = [(e.oid, e.points) for e in polys if e.flag == 0 and e.style != -3]
        if hint and hint.get("oids"):
            # GRAFIS keeps the same cut elements in every size of a part (verified: all 15 grading entries,
            # and against the AAMA export), so the element set found in another size is tried first; the
            # exhaustive search runs only if those elements do not form a simple closed ring here.
            contour = chain_elements([c for c in cand if c[0] in hint["oids"]])
            if contour is not None and (len(contour.points) < 3 or not _simple_ring(contour.points)):
                contour = None
        if contour is None:
            contour = outer_cycle(cand)
    if contour is None:
        issues.append(f"{src}: no closed cut contour found")
        return None
    ring = contour.points
    if ring_area(ring) < 0:
        ring = ring[::-1]
    cut_ids = set(contour.oids)
    if hint is not None:
        hint["oids"] = cut_ids
    g = PieceGeometry(size=size_name, cut=ring, source=src)
    by_oid = {e.oid: e for e in polys}
    for oid in contour.oids:
        e = by_oid.get(oid)
        if e is None:
            continue
        for q in (e.points[0], e.points[-1]):
            if all(math.dist(q, c) > 0.01 for c in g.corners):
                g.corners.append(tuple(q))
    g.completeness = {"cut": cut_status, "cut_method": cut_source}
    # style -7 = seam line; style -6 = net contour lying ON the cut line (no allowance, e.g. hem):
    # GRAFIS does not export -6 as seam (verified against its DXF), so it is not a separate seam line.
    seam_parts = [e for e in polys if e.style == -7 and e.oid not in cut_ids]
    if seam_parts:
        seam = chain_elements([(e.oid, e.points) for e in seam_parts])
        if seam is not None:
            g.seam.append(Polyline(seam.points, True, ",".join(map(str, seam.oids))))
        else:
            g.seam.extend(Polyline(list(e.points), False, str(e.oid)) for e in seam_parts)
        g.completeness["seam"] = Status.PROBABLE.value
    else:
        g.completeness["seam"] = Status.UNKNOWN.value
    grains = [e for e in polys if e.style == -3]
    if grains:
        best = max(grains, key=lambda e: sum(math.dist(a, b) for a, b in zip(e.points, e.points[1:])))
        g.grain = Polyline(list(best.points), False, str(best.oid))
        g.completeness["grain"] = Status.PROBABLE.value
    else:
        g.completeness["grain"] = Status.UNKNOWN.value
    from shapely.geometry import LinearRing, LineString, Point
    cut_ring = LinearRing(ring)
    for e in polys:
        if e.oid in cut_ids or e.style in (-7, -6, -3, 0):
            continue
        if e.role == "notch":
            # cut notch = notch element with one end ON the cut line; base on the line, pointing inward.
            # Verified against GRAFIS' own DXF export (44/1500 marker): 44 of 46 notch slits identical.
            a, b = e.points[0], e.points[-1]
            da, db = cut_ring.distance(Point(a)), cut_ring.distance(Point(b))
            if min(da, db) <= NOTCH_ON_CUT_TOL:
                if db < da:
                    a, b = b, a
                ln = math.dist(a, b) or 1.0
                g.notches.append(Notch(a, ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln), ln, str(e.oid)))
                continue
            # notch mark on the seam line: GRAFIS exports it with the seam (layer 8), never as a cut
            seam_lines = [LineString(s.points + ([s.points[0]] if s.closed else [])) for s in g.seam
                          if len(s.points) >= 2]
            sa = min((ln.distance(Point(a)) for ln in seam_lines), default=1.0)
            sb = min((ln.distance(Point(b)) for ln in seam_lines), default=1.0)
            if min(sa, sb) <= NOTCH_ON_CUT_TOL:
                g.seam.append(Polyline([a, b] if sa <= sb else [b, a], False, str(e.oid)))
                continue
            # other notch-type marks (e.g. fold line): drawn as internal lines, never cut
        g.internal.append(Polyline(list(e.points), False, str(e.oid)))
    g.completeness["notches"] = Status.PROBABLE.value if g.notches else Status.UNKNOWN.value
    g.completeness["internal"] = Status.PROBABLE.value
    for e in gb.elements:
        if e.kind == KIND_TEXT:
            anc = text_anchor(e)
            if anc and e.text:
                g.labels.append(Label(e.text, anc[0], anc[1], anc[2], text_angle(e)))
        elif e.kind == KIND_SYMBOL:
            pos = symbol_position(e)
            if pos:
                # kind 6 = measurement annotation: its value equals the #TFLIST measurement of the same
                # size (615/615 in the sample MDL); GRAFIS exports no drill holes for them (Bullmer, AAMA)
                g.measures.append(Label(e.text or "", pos, 0.0))
    g.completeness["labels"] = Status.PROBABLE.value if g.labels else Status.UNKNOWN.value
    g.completeness["measures"] = Status.CONFIRMED.value if g.measures else Status.UNKNOWN.value
    return g


def read_grafis(path: str, encoding: str = DEFAULT_ENCODING, include_construction: bool = True) -> ReadResult:
    cont = read_container(path)
    issues = list(cont.errors)
    tb = cont.get(2, 1, 0, 0)
    if tb is None:
        raise ValueError("text block (2,1,0,0) missing")
    ts = parse_text(tb.payload, encoding)
    kind = "scb" if "SBINFO" in ts.sections else "mdl"
    sizes = _size_names(ts)
    blocks = cont.by_id()
    proj = Project(name=os.path.splitext(os.path.basename(path))[0])
    proj.size_names = [sizes[i] for i in sorted(sizes) if i != 1]
    info = SourceInfo(path=os.path.abspath(path), kind=kind, sha256=cont.sha256, size=cont.size)
    if kind == "scb":
        info.internal_model_name = ts.sbinfo.get("MODEL")
        info.notes.append("internal MODEL name is informational; it is not used as a path")
    proj.sources.append(info)
    for t in ts.tlist:
        if not include_construction and not t.production:
            continue
        piece = Piece(uid=Piece.new_uid(), source_id=t.piece_id, number=t.number, name=t.name,
                      material=t.material, production=t.production,
                      default_count=t.count if t.count is not None else 1,
                      default_mirrored=t.mirrored if t.mirrored is not None else 0)
        hint: dict = {}
        for idx in sorted(sizes):
            b = blocks.get((3, t.number, 7, idx))
            if b is None:
                continue
            src = f"{kind.upper()} block (3,{t.number},7,{idx})"
            g = _build_piece_geometry(b.payload, sizes[idx], src, issues, hint)
            if g is not None:
                key = sizes[idx] if idx != 1 else f"base:{sizes[idx]}"
                piece.sizes[key] = g
        # A size whose #GRDTAB reference is the base entry (index 1) IS the base size: GRAFIS may store only the
        # base block for it (sample: size 28 -> ref "__HN40_0" = base). Use the base geometry for that size.
        base_entry = next((e for e in ts.sizes if e.index == 1), None)
        base_key = f"base:{base_entry.name}" if base_entry else None
        if base_key in piece.sizes:
            for e in ts.sizes:
                if e.index != 1 and e.name not in piece.sizes and e.ref and e.ref == base_entry.name:
                    piece.sizes[e.name] = piece.sizes[base_key]
                    piece.notes.append(f"size {e.name}: geometry of the base entry {base_entry.name} "
                                       f"(GRDTAB reference), no separate block stored")
        if not piece.sizes:
            piece.notes.append("no extractable geometry")
        angles = {grain_angle(g.grain.points) for g in piece.sizes.values() if g.grain}
        angles = {round(a, 3) for a in angles if a is not None}
        if len(angles) == 1:
            piece.grain_angle = angles.pop()
        proj.pieces.append(piece)
    res = ReadResult(proj, cont, ts, issues)
    if kind == "scb":
        _read_marker(res, blocks)
    return res


def _read_marker(res: ReadResult, blocks) -> None:
    ts, proj = res.text, res.project
    sb = ts.sbinfo
    mb = blocks.get((2, 8, 0, 0))
    if mb is None:
        res.issues.append("SCB without placement block (2,8,0,0)")
        return
    try:
        expected = int(sb.get("PCSTOTAL", "0"))
    except ValueError:
        expected = None
    hdr, recs, errs = decode_marker(mb.payload, expected or None)
    res.issues.extend(errs)
    width = float(sb.get("WIDTH", hdr.width))
    fabric = FabricSettings(width=width)
    sizes = _size_names(ts)
    by_num = {p.number: p for p in proj.pieces}
    marker = Marker(name=f"{proj.name} (original)", fabric=fabric, origin="original")
    checks = {"header_width": hdr.width, "header_length": hdr.length, "header_eff": hdr.efficiency,
              "records": len(recs), "bbox_mismatch": [], "area_mismatch": []}
    for r in recs:
        piece = by_num.get(r.part)
        size = sizes.get(r.size_index, str(r.size_index))
        if piece is None or size not in piece.sizes:
            res.issues.append(f"placement of part {r.part} size {size}: geometry not available")
            continue
        g = piece.sizes[size]
        bx = bbox(g.cut)
        if abs(bx[0] - r.xmin) > 0.01 or abs(bx[1] - r.ymin) > 0.01 or abs(bx[2] - bx[0] - r.bbox_w) > 0.01 \
                or abs(bx[3] - bx[1] - r.bbox_h) > 0.01:
            checks["bbox_mismatch"].append((r.part, size))
        if abs(abs(ring_area(g.cut)) / 1e6 - r.area_m2) > 1e-4:
            checks["area_mismatch"].append((r.part, size))
        rot = r.rotation
        pts = transform_points(g.cut, rot, r.mirror)
        tb = bbox(pts)
        pl = Placement(uid=Piece.new_uid(), piece_uid=piece.uid, size=size, bundle=r.bundle,
                       x=r.x - tb[0], y=r.y - tb[1], rotation=rot, mirrored=r.mirror)
        marker.placements.append(pl)
    marker.length = float(hdr.length) if hdr.length > 0 else float(sb.get("LENGTH", 0))
    marker.stats = {"grafis_" + k.lower(): v for k, v in sb.items()}
    proj.markers.append(marker)
    proj.sbinfo = dict(sb)
    # cut order recovered from #SBGRLST (bundles) and #SBTLIST (counts)
    q: dict[str, int] = {}
    for _n, s in ts.sbgrlst:
        q[s] = q.get(s, 0) + 1
    # "MATERIALO upper fabric": key suffix = material code used in #TLIST ("O"), value = material name
    mat_code = next((k[len("MATERIAL"):] for k in sb if k.startswith("MATERIAL") and len(k) > len("MATERIAL")), None)
    co = CutOrder(size_quantities=q, material=mat_code)
    by_num_uid = {p.number: p.uid for p in proj.pieces}
    for e in ts.sbtlist:
        if e.number in by_num_uid:
            co.piece_counts[by_num_uid[e.number]] = (e.count, e.mirrored)
    for p in proj.pieces:
        if p.uid not in co.piece_counts:
            co.piece_counts[p.uid] = (0, 0)
    proj.cut_order = co
    res.checks = checks


def read_mdl(path: str, **kw) -> ReadResult:
    return read_grafis(path, **kw)


def read_scb(path: str, **kw) -> ReadResult:
    return read_grafis(path, **kw)
