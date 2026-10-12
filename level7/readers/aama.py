"""AAMA/ASTM-style DXF + RUL import (additional path; NOT a substitute for native GRAFIS reading).

Implemented as written by GRAFIS (samples/reference/aama): one block per piece in the base size,
layer 1 = cut contour (POLYLINE) with grade-point rule numbers as TEXT "# n" placed on the vertices,
layer 7 = grain line, layer 14 = sew lines, layer 15 = base size name, TEXT "Piece Name:", "Category:",
"Quantity:". RUL: "SIZE LIST", "RULE:DELTA n" with one (dx, dy) per size.

Grading: graded points = base + delta(size). Vertices without a rule are moved by linear interpolation
(along the contour) of the deltas of the neighbouring graded points; this is the usual AAMA consumer
behaviour but is an approximation of GRAFIS' own curve grading (measured deviation is reported by tests).

GRAFIS quirk: the size list contains the sample size twice ("40 40"); in each rule exactly one of the two
columns is (0,0) = the base, the other is the real size. Both orders occur.
"""
from __future__ import annotations

import math
import os
import re

import ezdxf

from ..formats.grafis.container import sha256_bytes
from ..geometry import grain_angle, ring_area
from ..model import CutOrder, Notch, Piece, PieceGeometry, Polyline, Project, SourceInfo, Status


def read_rul(path: str):
    sizes, rules, sample, cur, vals = [], {}, None, None, []
    for ln in open(path, encoding="latin-1").read().splitlines():
        if ln.startswith("SIZE LIST:"):
            sizes = ln.split(":", 1)[1].split()
        elif ln.startswith("SAMPLE SIZE:"):
            sample = ln.split(":", 1)[1].strip()
        elif ln.startswith("RULE:DELTA"):
            if cur is not None:
                rules[cur] = vals
            cur, vals = int(ln.split()[-1]), []
        elif ln.startswith("END"):
            if cur is not None:
                rules[cur] = vals
            cur = None
        elif cur is not None:
            nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", ln)]
            vals += list(zip(nums[0::2], nums[1::2]))
    return sizes, sample, rules


def size_columns(sizes, sample):
    """Map size name -> column index; the duplicated sample size is resolved per rule (see module doc)."""
    cols = {}
    dup = [i for i, s in enumerate(sizes) if s == sample]
    for i, s in enumerate(sizes):
        if i not in dup:
            cols[s] = i
    return cols, dup


def _delta(rule, cols, dup, size, sample):
    if size == sample and len(dup) == 2:
        a, b = rule[dup[0]], rule[dup[1]]
        return b if a == (0.0, 0.0) else a
    return rule[cols[size]]


def _rule_points(ents, layer, pts, tol=0.01):
    out = {}
    for e in ents:
        if e.dxftype() == "TEXT" and e.dxf.layer == layer and e.dxf.text.startswith("#"):
            q = (e.dxf.insert.x, e.dxf.insert.y)
            i = min(range(len(pts)), key=lambda k: math.dist(pts[k], q))
            if math.dist(pts[i], q) <= tol:
                out[i] = int(e.dxf.text[1:].strip())
    return out


def read_aama(dxf_path: str, rul_path: str | None = None, encoding: str = "cp1256"):
    issues: list[str] = []
    if rul_path is None:
        cand = os.path.splitext(dxf_path)[0] + ".rul"
        rul_path = cand if os.path.exists(cand) else None
    sizes, sample, rules = read_rul(rul_path) if rul_path else ([], None, {})
    cols, dup = size_columns(sizes, sample) if sizes else ({}, [])
    size_names = sorted(set(sizes), key=lambda s: (len(s), s)) if sizes else ["base"]
    doc = ezdxf.readfile(dxf_path, encoding=encoding)   # GRAFIS writes Arabic names in Windows-1256
    with open(dxf_path, "rb") as fh:
        sha = sha256_bytes(fh.read())
    proj = Project(name=os.path.splitext(os.path.basename(dxf_path))[0], size_names=size_names)
    proj.sources.append(SourceInfo(os.path.abspath(dxf_path), "aama", sha, os.path.getsize(dxf_path),
                                   notes=["AAMA DXF + RUL import (GRAFIS export); not GRAFIS-native"]))
    for b in [b for b in doc.blocks if not b.name.startswith("*")]:
        ents = list(b)
        cut = [e for e in ents if e.dxftype() == "POLYLINE" and e.dxf.layer == "1"]
        if not cut:
            continue
        base = [(v.dxf.location.x, v.dxf.location.y) for v in cut[0].vertices]
        if len(base) > 2 and math.dist(base[0], base[-1]) < 1e-6:
            base = base[:-1]
        info = {}
        for e in ents:
            if e.dxftype() == "TEXT" and ":" in e.dxf.text and not e.dxf.text.startswith("#"):
                k, _, v = e.dxf.text.partition(":")
                info[k.strip()] = v.strip()
        graded = _rule_points(ents, "1", base)
        notch_pts = [(e.dxf.location.x, e.dxf.location.y) for e in ents
                     if e.dxftype() == "POINT" and e.dxf.layer == "4"]
        grain = None
        for e in ents:
            if e.dxftype() == "LINE" and e.dxf.layer == "7":
                grain = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        seams = []
        for e in ents:
            if e.dxftype() == "POLYLINE" and e.dxf.layer == "14":
                sp = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                seams.append((sp, _rule_points(ents, "14", sp)))
        name = info.get("Annotation") or info.get("Piece Name") or b.name
        num = None
        m = re.match(r"(\d+)", info.get("Piece Name", ""))
        if m:
            num = int(m.group(1))
        piece = Piece(uid=Piece.new_uid(), source_id=f"aama:{b.name}", number=num, name=name,
                      material=info.get("Category"), production=True)
        qty = int(info.get("Quantity", "1") or 1)
        piece.default_count, piece.default_mirrored = (1, 1) if qty == 2 else (qty, 0)
        targets = [s for s in size_names] if rules else ["base"]
        for s in targets:
            pts = _grade(base, graded, rules, cols, dup, s, sample) if rules else list(base)
            # notches (layer 4 points on the contour) follow the graded contour vertex
            notch_pos = []
            for q in notch_pts:
                i = min(range(len(base)), key=lambda k: math.dist(base[k], q))
                if math.dist(base[i], q) <= 0.01:
                    notch_pos.append(pts[i])
            spikes, pts = _strip_spikes(pts)
            if ring_area(pts) < 0:
                pts = pts[::-1]
            g = PieceGeometry(size=s, cut=pts, source=f"AAMA block {b.name}")
            g.notches = [Notch(a, ((t[0] - a[0]) / math.dist(a, t), (t[1] - a[1]) / math.dist(a, t)),
                               math.dist(a, t)) for a, t in spikes if math.dist(a, t) > 0]
            g.notches += [Notch(q, _inward(pts, q), 5.0) for q in notch_pos]
            g.seam = [Polyline(_grade(sp, rp, rules, cols, dup, s, sample, closed=False) if rules else sp)
                      for sp, rp in seams]
            if grain:
                g.grain = Polyline(grain)
            g.completeness = {"cut": Status.CONFIRMED.value if s == sample or not rules else Status.PROBABLE.value,
                              "grain": Status.CONFIRMED.value if grain else Status.UNKNOWN.value}
            piece.sizes[s] = g
        if grain:
            piece.grain_angle = grain_angle(grain)
        proj.pieces.append(piece)
    if not rules:
        issues.append("no .rul file: only the base size is available")
    proj.cut_order = CutOrder(size_quantities={s: 0 for s in proj.size_names},
                              piece_counts={p.uid: (p.default_count, p.default_mirrored) for p in proj.pieces})
    return proj, issues


def _inward(ring, q):
    """Unit normal pointing into the (counter-clockwise) ring at point q (AAMA notches carry no angle)."""
    n = len(ring)
    i = min(range(n), key=lambda k: math.dist(ring[k], q))
    a, b = ring[i - 1], ring[(i + 1) % n]
    tx, ty = b[0] - a[0], b[1] - a[1]
    L = math.hypot(tx, ty) or 1.0
    return (-ty / L, tx / L)


def _grade(base, graded, rules, cols, dup, size, sample, closed=True):
    n = len(base)
    deltas = {i: _delta(rules[r], cols, dup, size, sample) for i, r in graded.items() if r in rules}
    if not deltas:
        return list(base)
    idx = sorted(deltas)
    seg = [math.dist(base[i], base[(i + 1) % n]) for i in range(n)]
    out = []
    for i in range(n):
        if i in deltas:
            d = deltas[i]
        else:
            prev = max((k for k in idx if k < i), default=idx[-1] if closed else None)
            nxt = min((k for k in idx if k > i), default=idx[0] if closed else None)
            if prev is None or nxt is None:        # open polyline end without rule: take nearest delta
                d = deltas[nxt if prev is None else prev]
                out.append((base[i][0] + d[0], base[i][1] + d[1]))
                continue

            def arc(a, b):
                s, k = 0.0, a
                while k != b:
                    s += seg[k]
                    k = (k + 1) % n
                return s
            total = arc(prev, nxt)
            t = arc(prev, i) / total if total > 0 else 0.0
            d0, d1 = deltas[prev], deltas[nxt]
            d = (d0[0] + t * (d1[0] - d0[0]), d0[1] + t * (d1[1] - d0[1]))
        out.append((base[i][0] + d[0], base[i][1] + d[1]))
    return out


def _strip_spikes(pts, tol=1e-3):
    from .dxf import strip_spikes
    clean, spikes = strip_spikes(pts, tol)
    return spikes, clean
