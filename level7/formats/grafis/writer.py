"""GRAFIS SCB writer (template based, experimental until opened in GRAFIS by the user).

A LEVEL7 marker is written into a copy of a GRAFIS SCB of the same model (the template): every block that is
not understood (geometry, construction data, stamps) is copied byte for byte; only the marker placement block
(2,8,0,0) and the marker sections of the text block (#SBINFO, #SBGRLST, #SBTLIST) are rewritten.

Placement record fields written (see placements.py): part, GRDTAB size index, bbox w/h, bbox origin, X/Y of the
placed bbox, base rotation, flags (0x40 = extra 180 deg), mirror, running number (record + 1), area, record
number, rotation pivot (+64), extra rotation, copy number, bundle. Unknown bytes come from a template record
of the same part (same size and mirror when available).

Rotation pivot (+64), derived from both reference SCBs for base rotation -90 deg (all records):
    px = (ymax - xmax - xmin - ymin) / 2,   py = (xmax - xmin - ymin - ymax) / 2
Self-check: re-writing a GRAFIS marker unchanged reproduces the original file byte for byte (tests).
"""
from __future__ import annotations

import re
import struct

from ...geometry import bbox, placement_points, ring_area
from .container import BLOCK_MARK, TRAILER, read_container
from .placements import HDR, REC, decode_marker
from .textsections import parse_text

ENC = "cp1256"


class ScbWriteError(ValueError):
    pass


def pivot(xmin, ymin, w, h):
    xmax, ymax = xmin + w, ymin + h
    return (ymax - xmax - xmin - ymin) / 2.0, (xmax - xmin - ymin - ymax) / 2.0


def _f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def _sbinfo_set(lines, key, value):
    pat = re.compile(rf"^{key}(?![A-Z])")         # "PCSTOTAL28": no space between key and value
    for i, ln in enumerate(lines):
        if pat.match(ln):
            lines[i] = f"{key:<8}{value}"
            return
    lines.append(f"{key:<8}{value}")


def _replace_section(text: str, name: str, new_lines: list[str]) -> str:
    m = re.search(rf"(^|\r\n)#{name}\r\n(.*?)(?=\r\n#|\Z)", text, re.S)
    body = "\r\n".join(new_lines)
    if m is None:
        return text.replace("\r\n#ENDINFO", f"\r\n#{name}\r\n{body}\r\n#ENDINFO", 1)
    start = m.start(2)
    return text[:start] + body + text[m.end(2):]


def write_scb(template_path: str, project, marker, out_path: str) -> dict:
    """Write ``marker`` of ``project`` (read from a GRAFIS file of the same model) as a GRAFIS SCB."""
    if any(p.model for p in project.pieces):
        raise ScbWriteError("an SCB holds one model; this session contains several models")
    data = open(template_path, "rb").read()
    cont = read_container(template_path)
    blocks = cont.by_id()
    tb, mb = blocks.get((2, 1, 0, 0)), blocks.get((2, 8, 0, 0))
    if tb is None or mb is None:
        raise ScbWriteError("the template is not a GRAFIS marker file (SCB)")
    text = tb.payload.rstrip(b"\x00").decode(ENC)
    ts = parse_text(tb.payload)
    tlist = {e.number: e for e in ts.tlist}
    size_idx = {e.name: e.index for e in ts.sizes}
    total_t = int(ts.sbinfo.get("PCSTOTAL", "0") or 0)
    hdr, trecs, errs = decode_marker(mb.payload, total_t or None)
    if errs:
        raise ScbWriteError("template marker block: " + "; ".join(errs))
    by_key = {}
    for r in trecs:
        by_key.setdefault((r.part, r.size_index, r.mirror), r)
        by_key.setdefault((r.part, r.size_index), r)
        by_key.setdefault((r.part,), r)
    placed = [pl for pl in marker.placements if pl.placed]
    if not placed:
        raise ScbWriteError("the marker has no placed pieces")
    # GRAFIS numbers bundles through the whole marker (1..N); LEVEL7 numbers them per size
    order = {e.name: e.index for e in ts.sizes}
    gkeys = sorted({(pl.size, pl.bundle) for pl in placed}, key=lambda sb: (order.get(sb[0], 0), sb[1]))
    gbundle = {sb: k + 1 for k, sb in enumerate(gkeys)}
    recs, parts_used, area_sum = [], {}, 0.0
    for k, pl in enumerate(placed):
        gb = gbundle[(pl.size, pl.bundle)]
        piece = project.piece(pl.piece_uid)
        e = tlist.get(piece.number)
        if e is None or e.name.strip() != piece.name.strip():
            raise ScbWriteError(f"piece {piece.number} {piece.name!r} is not in the template SCB's piece list")
        if pl.size not in size_idx:
            raise ScbWriteError(f"size {pl.size!r} is not in the template SCB")
        si = size_idx[pl.size]
        g = piece.sizes[pl.size]
        bx = bbox(g.cut)
        w, h, xmin, ymin = bx[2] - bx[0], bx[3] - bx[1], bx[0], bx[1]
        pts = placement_points(g.cut, pl)
        X, Y = min(p[0] for p in pts), min(p[1] for p in pts)
        area = abs(ring_area(g.cut)) / 1e6
        area_sum += area
        same = [r for r in trecs if (r.part, r.size_index, r.mirror) == (e.number, si, pl.mirrored)]

        def same_angle(r):
            return abs(((pl.rotation - r.rotation) + 180.0) % 360.0 - 180.0) < 1e-6
        t = (next((r for r in same if same_angle(r) and r.bundle == gb), None)
             or next((r for r in same if same_angle(r)), None)
             or next((r for r in same if r.bundle == gb), None)
             or (same[0] if same else None)
             or by_key.get((e.number, si)) or by_key.get((e.number,)) or trecs[0])
        base = t.base_rot
        same_rot = abs(((pl.rotation - t.rotation) + 180.0) % 360.0 - 180.0) < 1e-6
        if same_rot:                     # keep GRAFIS' own representation (0x80 flag or extra 180 deg)
            extra, flags = t.extra_rot, t.flags
        else:
            r = (pl.rotation - base) % 360.0
            extra = 0.0 if abs(r) < 1e-6 or abs(r - 360) < 1e-6 else r
            flags = (t.flags & ~0xC0) | (0x40 if abs(extra - 180.0) < 1e-6 else 0)
        rec = bytearray(t.raw)
        struct.pack_into("<HH", rec, 0, e.number, si)
        if (t.part, t.size_index) == (e.number, si) and abs(_f32(t.xmin) - _f32(xmin)) < 1e-3:
            # same part and size as the template record: keep GRAFIS' own bbox / area / pivot values
            pass
        else:
            struct.pack_into("<4f", rec, 4, w, h, xmin, ymin)
            struct.pack_into("<f", rec, 44, area)
            if abs(base + 90.0) < 1e-6:
                struct.pack_into("<2f", rec, 64, *pivot(xmin, ymin, w, h))
        struct.pack_into("<2f", rec, 20, X, Y)
        struct.pack_into("<f", rec, 36, base)
        rec[40] = flags & 0xFF
        rec[41] = 1 if pl.mirrored else 0
        struct.pack_into("<H", rec, 42, k + 2)
        struct.pack_into("<I", rec, 56, k + 1)
        struct.pack_into("<f", rec, 84, extra)
        struct.pack_into("<HH", rec, 88, k + 1, gb)
        recs.append(bytes(rec))
        parts_used[e.number] = e
    width = marker.fabric.width
    length = max(max(px for px, _ in placement_points(project.piece(pl.piece_uid).sizes[pl.size].cut, pl))
                 for pl in placed)
    length = max(length, float(marker.length or 0.0)) if getattr(marker, "origin", "") == "original" else length
    eff = area_sum * 1e6 / (width * length) if width and length else 0.0
    head = bytearray(mb.payload[:HDR])
    unchanged = len(recs) == len(trecs) and all(a == b.raw for a, b in zip(recs, trecs)) \
        and abs(width - hdr.width) < 1e-3
    if unchanged:                        # the template's own marker: keep GRAFIS' header values
        length, eff = hdr.length, hdr.efficiency
    struct.pack_into("<f", head, 36, width)
    struct.pack_into("<I", head, 56, len(recs))
    if not unchanged:
        struct.pack_into("<2f", head, 72, eff, length)
    tail = mb.payload[HDR + REC * len(trecs):]
    new_marker = bytes(head) + b"".join(recs) + tail

    # text sections
    sb = re.search(r"#SBINFO\r\n(.*?)(?=\r\n#)", text, re.S)
    sblines = sb.group(1).split("\r\n") if sb else []
    bundles = sorted(gbundle.values())
    sizes_by_bundle = {b: sb[0] for sb, b in gbundle.items()}
    _sbinfo_set(sblines, "WIDTH", f"{width:.0f}")
    _sbinfo_set(sblines, "LENGTH", f"{length:.0f}")
    _sbinfo_set(sblines, "EFFCNCY", f"{eff * 100:.2f}")
    _sbinfo_set(sblines, "USDAREA", f"{area_sum:.2f}")
    _sbinfo_set(sblines, "PIECES", str(len(parts_used)))
    _sbinfo_set(sblines, "BUNDLES", str(len(bundles)))
    _sbinfo_set(sblines, "PCSTOTAL", str(len(recs)))
    _sbinfo_set(sblines, "PCSUNPLC", str(sum(1 for pl in marker.placements if not pl.placed)))
    new_text = _replace_section(text, "SBINFO", sblines)
    new_text = _replace_section(new_text, "SBGRLST", [f"{b:>3}     {sizes_by_bundle[b]}" for b in bundles])
    old_tl = {int(m.group(1)): ln for ln in (re.search(r"#SBTLIST\r\n(.*?)(?=\r\n#)", text, re.S) or [None, ""])[1]
              .split("\r\n") if (m := re.match(r"(\d{3}) ", ln))}
    counts = {}
    for pl in placed:
        n = project.piece(pl.piece_uid).number
        c = counts.setdefault(n, [set(), set()])
        c[1 if pl.mirrored else 0].add((pl.size, pl.bundle, pl.uid))
    tl_lines = []
    for n in sorted(parts_used):
        e = parts_used[n]
        garments = max(1, len({(pl.size, pl.bundle) for pl in placed if project.piece(pl.piece_uid).number == n}))
        nn, mm = len(counts[n][0]) // garments, len(counts[n][1]) // garments
        line = old_tl.get(n)
        if line:
            line = re.sub(r"^(\d{3} .*?)(\s+)(\d+)(\s+)(\d+)(\s+----)", lambda m: f"{m.group(1)}{m.group(2)}{nn}{m.group(4)}{mm}{m.group(6)}",
                          line, count=1)
        else:
            line = f"{n:03d} {e.name:<25}{nn}  {mm} ----x----    0    0    0    0    0    0 0"
        tl_lines.append(line)
    new_text = _replace_section(new_text, "SBTLIST", tl_lines)
    new_text_bytes = new_text.encode(ENC) + b"\x00"

    # rebuild the container: same order, same block stamps, new payloads where changed
    out = bytearray(data[:80])
    for b in cont.blocks:
        payload = b.payload
        if b.bid == (2, 8, 0, 0):
            payload = new_marker
        elif b.bid == (2, 1, 0, 0) and new_text_bytes.rstrip(b"\x00") != b.payload.rstrip(b"\x00"):
            payload = new_text_bytes
        pad = (-(32 + len(payload))) % 8
        payload = payload + b"\x00" * pad
        out += struct.pack("<II", b.check, (32 + len(payload)) // 8) + BLOCK_MARK + struct.pack("<4I", *b.bid)
        out += payload
    out += TRAILER
    struct.pack_into("<I", out, 4, (len(out) - 8) // 8)
    with open(out_path, "wb") as fh:
        fh.write(out)
    return {"placements": len(recs), "length": length, "efficiency": eff, "bytes": len(out)}
