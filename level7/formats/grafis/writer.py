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

import os
import re
import struct
from pathlib import Path

from ...geometry import bbox, placement_points, ring_area
from .container import BLOCK_MARK, TRAILER, grafis_check, read_container
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
    data = Path(template_path).read_bytes()
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
    pmap = part_map(project, ts.tlist, {pl.piece_uid for pl in placed})
    check_geometry(template_path, project, pmap, {(pl.piece_uid, pl.size) for pl in placed})
    if any(abs(pl.sx - 1.0) > 1e-9 or abs(pl.sy - 1.0) > 1e-9 for pl in placed):
        raise ScbWriteError("markers with shrinkage cannot be written as SCB yet (GRAFIS' shrinkage fields are "
                            "not decoded); save as LEVEL7 project or export PLT/DXF/ISO")
    # GRAFIS numbers bundles through the whole marker (1..N); LEVEL7 numbers them per size
    order = {e.name: e.index for e in ts.sizes}
    gkeys = sorted({(pl.size, pl.bundle) for pl in placed}, key=lambda sb: (order.get(sb[0], 0), sb[1]))
    gbundle = {sb: k + 1 for k, sb in enumerate(gkeys)}
    recs, parts_used, area_sum = [], {}, 0.0
    for k, pl in enumerate(placed):
        gb = gbundle[(pl.size, pl.bundle)]
        piece = project.piece(pl.piece_uid)
        e = pmap[piece.uid]
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
        n = pmap[pl.piece_uid].number
        c = counts.setdefault(n, [set(), set()])
        c[1 if pl.mirrored else 0].add((pl.size, pl.bundle, pl.uid))
    tl_lines = []
    for n in sorted(parts_used):
        e = parts_used[n]
        garments = max(1, len({(pl.size, pl.bundle) for pl in placed if pmap[pl.piece_uid].number == n}))
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

    new = {(2, 8, 0, 0): new_marker}
    if new_text_bytes.rstrip(b"\x00") != tb.payload.rstrip(b"\x00"):
        new[(2, 1, 0, 0)] = new_text_bytes
    out = rebuild_container(data, cont, new, ScbWriteError)
    write_atomic(out_path, out)
    return {"placements": len(recs), "length": length, "efficiency": eff, "bytes": len(out)}


def part_map(project, tlist, uids) -> dict:
    """piece uid -> the template's #TLIST entry of that part. Older GRAFIS keeps the model's part numbers in the
    SCB; GRAFIS 26 numbers the SCB's parts 1..n in model order (vest2027 sample: MDL 19, 21, 24 ... -> SCB 1, 2,
    3 ...). Same number and name first; otherwise the k-th part of that name in the model is the k-th part of
    that name in the SCB."""
    out = {}
    by_num = {e.number: e for e in tlist}
    named: dict[str, list] = {}
    for e in sorted(tlist, key=lambda e: e.number):
        named.setdefault(e.name.strip(), []).append(e)
    model_named: dict[str, list] = {}
    for pc in sorted(project.pieces, key=lambda p: p.number or 0):
        model_named.setdefault(pc.name.strip(), []).append(pc)
    exact = all(by_num.get(project.piece(u).number) is not None and
                by_num[project.piece(u).number].name.strip() == project.piece(u).name.strip() for u in uids)
    for u in uids:
        pc = project.piece(u)
        if exact:
            out[u] = by_num[pc.number]
            continue
        # k-th of the same name among the parts this model produces (GRAFIS 26 lists only those in the SCB)
        same = [p for p in model_named[pc.name.strip()] if p.production or p.uid in uids]
        cands = named.get(pc.name.strip(), [])
        k = same.index(pc)
        if len(same) != len(cands) or k >= len(cands):
            raise ScbWriteError(f"piece {pc.number} {pc.name!r} is not in the template SCB's piece list")
        out[u] = cands[k]
    return out


def check_geometry(template_path, project, pmap, used) -> None:
    """The SCB carries its own copy of every part's geometry: it must be the session's geometry (otherwise the
    model changed after that SCB was saved and GRAFIS would show other shapes at the written positions)."""
    from ...readers.grafis import read_grafis
    tp = {p.number: p for p in read_grafis(template_path).project.pieces}
    for uid, size in used:
        pc = project.piece(uid)
        t = tp.get(pmap[uid].number)
        g, tg = pc.sizes.get(size), (t.sizes.get(size) if t is not None else None)
        if g is None or tg is None:
            raise ScbWriteError(f"piece {pc.name!r} size {size}: not in the template SCB")
        if max(abs(a - b) for a, b in zip(bbox(g.cut), bbox(tg.cut))) > 0.05 or \
                abs(abs(ring_area(g.cut)) - abs(ring_area(tg.cut))) > 1.0:
            raise ScbWriteError(f"piece {pc.name!r} size {size}: the template SCB's copy of this part differs from "
                                f"the model (changed after that SCB was saved) - save a new SCB of this model "
                                f"from GRAFIS and use it")


def rebuild_container(data: bytes, cont, new_payloads: dict, error=ScbWriteError) -> bytes:
    """The container again, same block order; blocks in ``new_payloads`` get the new payload and a recomputed
    check value (GRAFIS verifies it: a stale value made GRAFIS report "Style cannot be read ... corrupt file").
    Every other block is copied byte for byte."""
    out = bytearray(data[:80])
    for b in cont.blocks:
        payload = new_payloads.get(b.bid, b.payload)
        pad = (-(32 + len(payload))) % 8
        payload = payload + b"\x00" * pad
        head = struct.pack("<II", 0, (32 + len(payload)) // 8) + BLOCK_MARK + struct.pack("<4I", *b.bid)
        check = b.check
        if head[4:] + payload != data[b.offset + 4:b.offset + b.size]:          # block changed
            original = b"\0\0\0\0" + data[b.offset + 4:b.offset + b.size]
            if grafis_check(original) != b.check:
                raise error(f"cannot compute the GRAFIS check value of block {b.bid} - not written")
            check = grafis_check(head + payload)
        out += struct.pack("<I", check) + head[4:] + payload
    out += TRAILER
    struct.pack_into("<I", out, 4, (len(out) - 8) // 8)
    original_head = b"\0\0\0\0" + data[4:80]
    if grafis_check(original_head) != struct.unpack_from("<I", data, 0)[0]:
        raise error("cannot compute the GRAFIS file header check value - not written")
    struct.pack_into("<I", out, 0, 0)
    struct.pack_into("<I", out, 0, grafis_check(bytes(out[:80])))
    return bytes(out)


def write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".part"                 # the GRAFIS file is replaced only once the new one is complete
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
