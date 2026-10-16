"""Independent marker validation.

Works on the ORIGINAL cut contours (never on the search approximations used by the
engine) with shapely, so it is independent from the nesting implementation. Every
automatic or manual layout goes through ``validate_marker``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from shapely.geometry import Polygon, box
from shapely.strtree import STRtree

from ..geometry import grain_angle, grow_rect, placement_points
from ..model import LayType, Marker, Project

AREA_TOL = 0.01     # mm^2 overlap area tolerated (numerical noise)
DIST_TOL = 0.02     # mm tolerance on spacing / borders


@dataclass
class Issue:
    kind: str           # overlap / spacing / outside / rotation / mirror / count / geometry / grain / match
    message: str
    placements: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    ok: bool
    issues: list[Issue]
    checked: int
    length: float

    def summary(self) -> str:
        if self.ok:
            return f"valid: {self.checked} placements, no overlap/out-of-bounds/orientation issues"
        c = Counter(i.kind for i in self.issues)
        return "INVALID: " + ", ".join(f"{k}={v}" for k, v in c.items())


def placed_polygons(project: Project, marker: Marker) -> dict[str, Polygon]:
    out = {}
    for pl in marker.placements:
        if not pl.placed:
            continue
        g = project.piece(pl.piece_uid).sizes[pl.size]
        poly = Polygon(placement_points(g.cut, pl))
        if not poly.is_valid:
            poly = poly.buffer(0)
        out[pl.uid] = poly
    return out


def validate_marker(project: Project, marker: Marker, required: dict | None = None,
                    allowed_rotations: dict | None = None, allow_mirror_extra: bool = False) -> ValidationReport:
    """``required``: {(piece_uid, size, mirrored): count} expected copies (placed + reported unplaced).
    ``allowed_rotations``: {(piece_uid, mirrored): [deg,...]} if orientation must be checked."""
    issues: list[Issue] = []
    f = marker.fabric
    polys = placed_polygons(project, marker)
    uids = list(polys)
    geoms = [polys[u] for u in uids]
    length = max((g.bounds[2] for g in geoms), default=f.margin_start) + f.margin_end
    # geometry preserved (rigid motion => same area)
    for pl in marker.placements:
        if pl.uid in polys:
            orig = abs(Polygon(project.piece(pl.piece_uid).sizes[pl.size].cut).area) * pl.sx * pl.sy
            if abs(polys[pl.uid].area - orig) > 1e-6 * max(orig, 1.0) + 1e-6:
                issues.append(Issue("geometry", f"area changed for {pl.uid}", [pl.uid]))
    # bounds
    y0 = f.margin_left
    y1 = f.margin_left + f.usable_width
    x0 = f.margin_start
    x1 = (f.max_length - f.margin_end) if f.max_length else float("inf")
    for u, g in zip(uids, geoms):
        bx = g.bounds
        if bx[1] < y0 - DIST_TOL or bx[3] > y1 + DIST_TOL or bx[0] < x0 - DIST_TOL or bx[2] > x1 + DIST_TOL:
            issues.append(Issue("outside", f"{u} outside usable area: bounds {tuple(round(v, 2) for v in bx)}", [u]))
    # overlap / spacing
    tree = STRtree(geoms)
    sp = f.spacing
    # directional buffers: the other piece must stay out of this one grown by (buffer_x, buffer_y) (+ spacing)
    bx, by = max(0.0, f.buffer_x - DIST_TOL), max(0.0, f.buffer_y - DIST_TOL)
    for i, g in enumerate(geoms):
        gr = grow_rect(g, bx, by) if (bx > 0 or by > 0) else None
        cand = tree.query((gr or g).buffer(sp + DIST_TOL) if sp > 0 else (gr or g))
        for j in cand:
            j = int(j)
            if j <= i:
                continue
            h = geoms[j]
            inter = g.intersection(h).area
            if inter > AREA_TOL:
                issues.append(Issue("overlap", f"{uids[i]} overlaps {uids[j]} by {inter:.2f} mm2", [uids[i], uids[j]]))
                continue
            if sp > 0:
                d = g.distance(h)
                if d < sp - DIST_TOL:
                    issues.append(Issue("spacing", f"{uids[i]} - {uids[j]} distance {d:.3f} < {sp}",
                                        [uids[i], uids[j]]))
                    continue
            if gr is not None:
                bad = gr.distance(h) < sp - DIST_TOL if sp > 0 else gr.intersection(h).area > AREA_TOL
                if bad:
                    issues.append(Issue("spacing", f"{uids[i]} - {uids[j]} closer than buffer X {f.buffer_x} / "
                                                   f"Y {f.buffer_y} mm", [uids[i], uids[j]]))
    # orientation
    if allowed_rotations is not None:
        for pl in marker.placements:
            if not pl.placed:
                continue
            allowed = allowed_rotations.get((pl.piece_uid, pl.mirrored))
            if allowed is not None and not any(abs(((pl.rotation - a + 180) % 360) - 180) < 1e-6 for a in allowed):
                issues.append(Issue("rotation", f"{pl.uid} rotation {pl.rotation} not in {allowed}", [pl.uid]))
    # plaid / stripe matching: matched anchors on their pattern lines
    if f.repeat_x > 0 or f.repeat_y > 0:
        from ..matching import TOL_MM, placement_error
        for pl in marker.placements:
            if not pl.placed:
                continue
            e = placement_error(project.piece(pl.piece_uid), pl, f)
            if e is None:
                continue
            bad = [f"{n} {v:+.2f} mm" for n, v in zip(("X", "Y"), e) if v is not None and abs(v) > TOL_MM]
            if bad:
                issues.append(Issue("match", f"{pl.uid} not on the pattern: " + ", ".join(bad), [pl.uid]))
    # grain parallel to marker length (only when grain was read)
    for pl in marker.placements:
        if not pl.placed:
            continue
        g = project.piece(pl.piece_uid).sizes[pl.size]
        if g.grain is not None:
            ang = grain_angle(placement_points(g.grain.points, pl))
            turned = allowed_rotations is not None and any(           # a rotation this nesting was allowed (90 deg)
                min(abs(r - pl.rotation) % 360, 360 - abs(r - pl.rotation) % 360) < 1e-6
                for r in allowed_rotations.get((pl.piece_uid, pl.mirrored), ()))
            if turned and ang is not None and abs(ang - 90) <= 0.01:
                continue
            if ang is not None and min(ang, 180 - ang) > 0.01:
                issues.append(Issue("grain", f"{pl.uid} grain at {ang:.2f} deg to marker length", [pl.uid]))
    # copies
    if required is not None:
        have = Counter((pl.piece_uid, pl.size, pl.mirrored) for pl in marker.placements)
        for key, n in required.items():
            if have.get(key, 0) != n:
                issues.append(Issue("count", f"{key}: {have.get(key, 0)} placements, expected {n}"))
        for key in have:
            if key not in required:
                issues.append(Issue("count", f"{key}: unexpected placements"))
    return ValidationReport(not issues, issues, len(geoms), length)


def marker_stats(project: Project, marker: Marker) -> dict:
    """Utilisation = area of the union of placed cut regions / (width x length) * 100.

    Denominator variants are both reported: total fabric width and usable width.
    Holes in pieces are subtracted (cut-outs are waste). Length is measured from the
    marker origin (x = 0) to the right-most piece plus the end margin.
    """
    from shapely.ops import unary_union
    polys = list(placed_polygons(project, marker).values())
    f = marker.fabric
    u = unary_union(polys) if polys else Polygon()
    area = u.area
    if f.lay_type == LayType.FOLDED:          # nested on the half width, every piece cut twice (both halves)
        area *= 2.0
    length = (max((p.bounds[2] for p in polys), default=0.0) + f.margin_end) if polys else 0.0
    tot = f.width * length
    usable = f.usable_width * length
    eff_total = 100 * area / tot if tot else 0.0
    if f.lay_type == LayType.FOLDED:
        usable *= 2.0
    eff_usable = 100 * area / usable if usable else 0.0
    by_size = Counter(pl.size for pl in marker.placements if pl.placed)
    garments = len({(pl.size, pl.bundle) for pl in marker.placements if pl.placed})
    return {
        "length_mm": length,
        "width_mm": f.width,
        "usable_width_mm": f.usable_width,
        "pieces_area_m2": area / 1e6,
        "efficiency_total_width_pct": eff_total,
        "efficiency_usable_width_pct": eff_usable,
        "waste_pct": 100 - eff_total,
        "consumption_m": length / 1000.0,
        "consumption_yd": length / 914.4,
        "garments": garments,
        "length_per_garment_m": (length / 1000.0 / garments) if garments else 0.0,   # GRAFIS "U/B"
        "placed": sum(1 for p in marker.placements if p.placed),
        "unplaced": sum(1 for p in marker.placements if not p.placed),
        "by_size": dict(by_size),
        "definition": "union(placed cut areas) / (fabric width x marker length); width = total and usable",
    }


_ = box  # re-export convenience
