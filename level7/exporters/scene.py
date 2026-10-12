"""Exporter-neutral scene: marker -> layered entities in marker coordinates (mm).

Changing the export format never re-runs nesting: every exporter consumes this scene.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..geometry import bbox, placement_points
from ..model import Marker, Project

LAYERS = ("CUT", "SEAM", "INTERNAL", "NOTCH", "MARK", "GRAIN", "TEXT", "PIECE_NAME", "BORDER")


@dataclass
class Path:
    layer: str
    points: list[tuple[float, float]]
    closed: bool = False
    owner: str | None = None   # placement uid
    corners: list = field(default_factory=list)   # CUT only: element junctions (preferred cut start points)


@dataclass
class Text:
    layer: str
    text: str
    position: tuple[float, float]
    height: float
    owner: str | None = None
    rotation: float = 0.0


@dataclass
class Point:
    layer: str
    position: tuple[float, float]
    code: str | None = None
    owner: str | None = None


@dataclass
class Scene:
    paths: list[Path] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    width: float = 0.0
    length: float = 0.0

    def extent(self):
        pts = [p for path in self.paths for p in path.points] + [t.position for t in self.texts]
        return bbox(pts) if pts else (0.0, 0.0, 0.0, 0.0)


def marker_scene(project: Project, marker: Marker, include_labels: bool = True, include_border: bool = True,
                 label_size: bool = True) -> Scene:
    sc = Scene(width=marker.fabric.width, length=marker.length)
    for pl in marker.placements:
        if not pl.placed:
            continue
        piece = project.piece(pl.piece_uid)
        g = piece.sizes[pl.size]
        sc.paths.append(Path("CUT", placement_points(g.cut, pl), True, pl.uid,
                             placement_points(g.corners, pl) if g.corners else []))
        for h in g.holes:
            sc.paths.append(Path("CUT", placement_points(h, pl), True, pl.uid))
        for s in g.seam:
            sc.paths.append(Path("SEAM", placement_points(s.points, pl), s.closed, pl.uid))
        for s in g.internal:
            sc.paths.append(Path("INTERNAL", placement_points(s.points, pl), s.closed, pl.uid))
        for n in g.notches:
            a = n.position
            d = n.direction or (0.0, 0.0)
            b = (a[0] + d[0] * n.length, a[1] + d[1] * n.length)
            sc.paths.append(Path("NOTCH", placement_points([a, b], pl), False, pl.uid))
        for dr in g.drills:
            sc.points.append(Point("MARK", placement_points([dr.position], pl)[0], dr.code, pl.uid))
        if g.grain is not None:
            sc.paths.append(Path("GRAIN", placement_points(g.grain.points, pl), False, pl.uid))
        for lb in g.labels:
            # GRAFIS keeps texts readable on mirrored copies: anchor at the top of the frame, turned 180 deg
            ang = getattr(lb, "angle", 0.0)
            if pl.mirrored and lb.box:
                anchor = (lb.position[0], lb.box[3] - (lb.position[1] - lb.box[1]))
                rot = pl.rotation + 180.0 - ang
            else:
                anchor, rot = lb.position, pl.rotation + ang
            sc.texts.append(Text("TEXT", lb.text, placement_points([anchor], pl)[0], lb.height, pl.uid,
                                 rot % 360.0))
        if include_labels:
            c = placement_points([_inner_point(g.cut)], pl)[0]
            txt = f"{piece.name} {pl.size}" if label_size else piece.name
            if pl.mirrored:
                txt += " (M)"
            sc.texts.append(Text("PIECE_NAME", txt, c, 12.0, pl.uid))
    if include_border:
        L, W = marker.length, marker.fabric.width
        sc.paths.append(Path("BORDER", [(0, 0), (L, 0), (L, W), (0, W)], True, None))
    return sc


def piece_scene(project: Project, piece_uid: str, size: str) -> Scene:
    from ..model import Placement
    pl = Placement(uid="piece", piece_uid=piece_uid, size=size)
    m = Marker(name="piece", fabric=None, placements=[pl])  # type: ignore[arg-type]
    m.length = 0.0

    class _F:
        width = 0.0
    m.fabric = _F()  # type: ignore[assignment]
    return marker_scene(project, m, include_border=False)


def _inner_point(ring):
    from shapely.geometry import Polygon
    p = Polygon(ring)
    if not p.is_valid:
        p = p.buffer(0)
    q = p.representative_point()
    return (q.x, q.y)
