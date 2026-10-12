"""Evaluated part geometry, block (3, part, 7, size_index).

One block per part and GRDTAB size entry. Layout (verified on all 450 geometry
blocks of both samples: record count, pool length and per-element bounding boxes):

    u32 nrec
    u32 total payload length in 8-byte units
    nrec * 40-byte element records:
        u32 object id            (e.g. 2001..; shared between sizes and MDL/SCB)
        u32 flag                 (0 or 2; 2 => a 16-byte auxiliary item precedes the data)
        u32 aux pointer          (0 when flag == 0)
        u32 count                (number of 8-byte words of element data)
        u32 data pointer         (internal address, not a file offset; not needed)
        u8  kind                 (2 = polyline, 4 = text, 6 = symbol)
        u8  unknown (always 2 in samples)
        i16 style                (see LINE_STYLE)
        4*f32 bounding box (xmin, ymin, xmax, ymax), same unit as points
    data pool: for each record in order: [16-byte aux if flag==2] + count*8 bytes
        kind 2: count points (f32 x, f32 y)

Pattern coordinates are millimetres (see docs/GRAFIS_FORMAT.md, "units").
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

KIND_POLYLINE = 2
KIND_TEXT = 4
KIND_SYMBOL = 6

# style codes -> role. Status: "confirmed" only for 0 (cut line written by GRAFIS
# into the marker file for the nested size); the others are probable, from geometry.
LINE_STYLE = {
    0: "cut",        # confirmed: SCB flags exactly these objects of the nested size
    -7: "seam",      # probable: closed net contour inside the cut line
    -6: "seam",      # probable: net contour segment coinciding with an edge (hem)
    -3: "grain",     # probable: arrow-shaped polyline
    1: "internal",   # generic drawn line (internal lines, notches, construction remains)
}


@dataclass
class Element:
    oid: int
    flag: int
    count: int
    kind: int
    style: int
    bbox: tuple[float, float, float, float]
    aux: bytes = b""
    raw: bytes = b""
    points: list[tuple[float, float]] = field(default_factory=list)
    text: str | None = None
    bbox_ok: bool | None = None

    @property
    def role(self) -> str:
        if self.kind == KIND_TEXT:
            return "text"
        if self.kind == KIND_SYMBOL:
            return "symbol"
        if self.flag == 2 and self.count == 2 and self.style == 1:
            return "notch"   # probable: 2-point marks with aux item, ~5 mm, on contour
        return LINE_STYLE.get(self.style, "unknown")


@dataclass
class GeometryBlock:
    elements: list[Element]
    errors: list[str]


def decode_geometry(payload: bytes) -> GeometryBlock:
    errors: list[str] = []
    if len(payload) < 8:
        return GeometryBlock([], ["geometry block too short"])
    nrec, units = struct.unpack_from("<II", payload, 0)
    if units * 8 != len(payload):
        errors.append(f"length field {units * 8} != payload {len(payload)}")
    if 8 + 40 * nrec > len(payload):
        return GeometryBlock([], errors + [f"record table ({nrec}) exceeds block"])
    elems = []
    for i in range(nrec):
        o = 8 + 40 * i
        oid, flag, _aux, cnt, _ptr = struct.unpack_from("<5I", payload, o)
        kind, _u, style = struct.unpack_from("<BBh", payload, o + 20)
        bbox = struct.unpack_from("<4f", payload, o + 24)
        elems.append(Element(oid, flag, cnt, kind, style, bbox))
    off = 8 + 40 * nrec
    for e in elems:
        if e.flag == 2:
            e.aux = payload[off:off + 16]
            off += 16
        n = 8 * e.count
        if off + n > len(payload):
            errors.append(f"object {e.oid}: data exceeds block")
            break
        e.raw = payload[off:off + n]
        off += n
        if e.kind == KIND_POLYLINE:
            e.points = [struct.unpack_from("<2f", e.raw, 8 * k) for k in range(e.count)]
            if e.points:
                xs = [p[0] for p in e.points]
                ys = [p[1] for p in e.points]
                bb = (min(xs), min(ys), max(xs), max(ys))
                e.bbox_ok = all(abs(a - b) <= 1e-3 for a, b in zip(bb, e.bbox))
                if not e.bbox_ok:
                    errors.append(f"object {e.oid}: point bbox differs from stored bbox")
        elif e.kind == KIND_TEXT:
            e.text = _extract_ascii(e.raw[48:])
        elif e.kind == KIND_SYMBOL:
            e.text = _extract_ascii(e.raw[40:128])
    if off != len(payload) and not errors:
        errors.append(f"data pool ends at {off}, block length {len(payload)}")
    return GeometryBlock(elems, errors)


def _extract_ascii(b: bytes) -> str:
    s = b.split(b"\x00")[0].decode("cp1256", errors="replace").strip()
    return s


def text_anchor(e: Element) -> tuple[tuple[float, float], float] | None:
    """Text elements: first two f32 pairs are box corners, then (height?, width?) [probable]."""
    if e.kind != KIND_TEXT or len(e.raw) < 24:
        return None
    x0, y0, x1, y1, h1, h2 = struct.unpack_from("<6f", e.raw, 0)
    return ((min(x0, x1), min(y0, y1)), h1)


def symbol_position(e: Element) -> tuple[float, float] | None:
    """Symbols: position at word 3 (f32 x, f32 y) = degenerate stored bbox [confirmed by bbox]."""
    if e.kind != KIND_SYMBOL or len(e.raw) < 32:
        return None
    return struct.unpack_from("<2f", e.raw, 24)
