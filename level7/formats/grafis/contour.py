"""Cut-contour reconstruction from element graphs.

Method: build a graph whose nodes are element end points (merged within ``tol``) and
whose edges are whole polyline elements; enumerate simple cycles and take the one
with the largest enclosed area.

Evidence: for size 44 this selects exactly the object-id set that GRAFIS itself
flagged as cut line (style 0) in the marker file, for all 9 placed parts, and the
same id set is selected in all 15 grading entries of every production part.
Area and bounding box equal the values stored by GRAFIS in the marker records.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Contour:
    oids: list[int]
    points: list[tuple[float, float]]   # closed ring without repeated end point
    area: float


def _ring_area(pts):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return a / 2.0


def _simple(pts) -> bool:
    try:
        from shapely.geometry import Polygon
        return Polygon(pts).is_valid
    except Exception:  # pragma: no cover
        return True


def chain_elements(segments: list[tuple[int, list[tuple[float, float]]]], tol: float = 0.05) -> Contour | None:
    """Chain the given elements end-to-end into one closed ring (all must be used)."""
    if not segments:
        return None
    segs = [(oid, list(p)) for oid, p in segments if len(p) >= 2]
    oid0, ring = segs.pop(0)
    oids = [oid0]
    while segs:
        end = ring[-1]
        for i, (oid, s) in enumerate(segs):
            if math.dist(s[0], end) < tol:
                ring += s[1:]
                break
            if math.dist(s[-1], end) < tol:
                ring += s[::-1][1:]
                break
        else:
            return None
        oids.append(oid)
        segs.pop(i)
    if math.dist(ring[0], ring[-1]) >= tol:
        return None
    ring = ring[:-1]
    return Contour(oids, ring, abs(_ring_area(ring)))


def outer_cycle(segments: list[tuple[int, list[tuple[float, float]]]], tol: float = 0.05,
                max_steps: int = 300000) -> Contour | None:
    nodes: list[tuple[float, float]] = []

    def nid(p):
        for i, q in enumerate(nodes):
            if math.dist(p, q) < tol:
                return i
        nodes.append(p)
        return len(nodes) - 1

    edges = []
    best: list[Contour | None] = [None]
    for oid, pts in segments:
        if len(pts) < 2:
            continue
        a, b = nid(pts[0]), nid(pts[-1])
        if a == b:
            ring = list(pts[:-1])
            if len(ring) >= 3 and _simple(ring):
                c = Contour([oid], ring, abs(_ring_area(ring)))
                if best[0] is None or c.area > best[0].area:
                    best[0] = c
            continue
        edges.append((oid, a, b, list(pts)))
    adj: dict[int, list[int]] = {}
    for i, (_o, a, b, _p) in enumerate(edges):
        adj.setdefault(a, []).append(i)
        adj.setdefault(b, []).append(i)
    seen: set[frozenset] = set()
    steps = [0]

    def dfs(start, node, used, visited, ring, ids):
        steps[0] += 1
        if steps[0] > max_steps:
            return
        for ei in adj.get(node, []):
            if ei in used:
                continue
            oid, a, b, pts = edges[ei]
            nxt = b if a == node else a
            seg = pts if a == node else pts[::-1]
            if nxt == start:
                key = frozenset(ids + [oid])
                if key in seen:
                    continue
                seen.add(key)
                r = (ring + seg[1:])[:-1]
                if len(r) >= 3:
                    area = abs(_ring_area(r))
                    if (best[0] is None or area > best[0].area) and _simple(r):
                        best[0] = Contour(ids + [oid], r, area)
                continue
            if nxt in visited:
                continue
            dfs(start, nxt, used | {ei}, visited | {nxt}, ring + seg[1:], ids + [oid])

    for s in list(adj):
        dfs(s, s, frozenset(), {s}, [nodes[s]], [])
    return best[0]
