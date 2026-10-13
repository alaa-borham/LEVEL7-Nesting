"""Plaid / stripe matching.

The fabric pattern repeats every ``repeat_x`` mm along the marker length (vertical lines) and every ``repeat_y``
mm across the width (horizontal lines); the first lines lie at ``repeat_offset_x`` / ``repeat_offset_y`` from the
fabric start / edge (marker coordinates). A piece with a match rule has an anchor - one of its notches or corners,
which exist in every size - that must be placed ``dx`` after a vertical line (rule "x") and / or ``dy`` above a
horizontal line (rule "y"). Pieces matched this way line up with the pattern and therefore with each other
(e.g. front left / right, sleeve to front with an offset). The geometry of the pieces is never changed.
"""
from __future__ import annotations

from .geometry import placement_points
from .model import FabricSettings, Piece, Placement

TOL_MM = 0.5            # validation tolerance of a matched anchor to its pattern line


def anchor(piece: Piece, size: str):
    """Anchor point of the piece's match rule in pattern coordinates for ``size`` (None: no rule / not found)."""
    m = piece.match
    if not m or size not in piece.sizes:
        return None
    g = piece.sizes[size]
    i = int(m.get("index", -1))
    if m.get("kind") == "notch":
        return tuple(g.notches[i].position) if 0 <= i < len(g.notches) else None
    if m.get("kind") == "corner":
        return tuple(g.corners[i]) if 0 <= i < len(g.corners) else None
    return None


def rules(piece: Piece, fabric: FabricSettings) -> tuple[bool, bool]:
    """(match along x, match along y) that apply with this fabric."""
    m = piece.match or {}
    return bool(m.get("x")) and fabric.repeat_x > 0, bool(m.get("y")) and fabric.repeat_y > 0


def active(piece: Piece, fabric: FabricSettings) -> bool:
    return any(rules(piece, fabric))


def line_error(v: float, origin: float, repeat: float) -> float:
    """Signed distance of ``v`` to the nearest line origin + k * repeat."""
    r = (v - origin) % repeat
    return r if r <= repeat / 2 else r - repeat


def targets(fabric: FabricSettings, piece: Piece) -> tuple[float, float]:
    """Marker x / y of the pattern line the anchor must sit on (plus k * repeat)."""
    m = piece.match or {}
    return fabric.repeat_offset_x + float(m.get("dx", 0.0)), fabric.repeat_offset_y + float(m.get("dy", 0.0))


def placement_error(piece: Piece, pl: Placement, fabric: FabricSettings):
    """(ex, ey) in mm for a placed copy (None where the rule does not apply), or None without a rule / anchor."""
    a = anchor(piece, pl.size)
    if a is None or not active(piece, fabric):
        return None
    (x, y), = placement_points([a], pl)
    rx, ry = rules(piece, fabric)
    tx, ty = targets(fabric, piece)
    return (line_error(x, tx, fabric.repeat_x) if rx else None, line_error(y, ty, fabric.repeat_y) if ry else None)


def snap(piece: Piece, pl: Placement, fabric: FabricSettings) -> tuple[float, float]:
    """Shift (dx, dy) that puts the copy's anchor on its nearest pattern line(s)."""
    e = placement_error(piece, pl, fabric)
    if e is None:
        return 0.0, 0.0
    return -(e[0] or 0.0), -(e[1] or 0.0)
