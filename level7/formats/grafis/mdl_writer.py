"""GRAFIS MDL writer: the parts' material, production flag and copies (experimental until opened in GRAFIS).

The MDL the session was read from is the template. Only two things are changed per part; every other block
(geometry, construction, measurements) is copied byte for byte:

* the part's line in #TLIST (text block (2,1,0,0)): the production column ``  x O 01 01`` (material, copies,
  mirrored copies) or 12 spaces for a part that is not produced;
* the material record in block (3, part, 6, 6). The block is a list of records ``u16 units, u16 type`` of
  ``8 * units`` bytes. Type 1 is the material record (both sample MDLs, every part):

      +4  u8   0xFF = production part, 0x00 = not produced
      +5  char material code ("O", "F", "E", "S"; " " = none)
      +6  u16  copies in total (normal + mirrored)          ("O 01 01" -> 2 / 1, "O 01 00" -> 1 / 0)
      +8  u16  mirrored copies
      +10 u16  unknown, constant per material (O 2, F/E/S 1, none 0) - copied from a part of that material
      +12 u16  1 = production part
      +14 u16  0
      +16      material name, NUL terminated, space padded ("upper fabric", "lining", "fuse", "template")

A material code is written only when the file already has a part of that material (its record is the
pattern: unknown field and name). New codes need a GRAFIS file that uses them.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from .container import read_container
from .textsections import parse_text
from .writer import ENC, rebuild_container, write_atomic

MAT_BLOCK = (6, 6)


class MdlWriteError(ValueError):
    pass


def _records(payload: bytes, bid) -> list[bytes]:
    out, k = [], 0
    while k < len(payload):
        if k + 4 > len(payload):
            raise MdlWriteError(f"block {bid}: record list cut off")
        n = struct.unpack_from("<H", payload, k)[0]
        if n == 0:
            if payload[k:].strip(b"\x00"):
                raise MdlWriteError(f"block {bid}: unknown record layout")
            break
        if k + 8 * n > len(payload):
            raise MdlWriteError(f"block {bid}: record longer than the block")
        out.append(payload[k:k + 8 * n])
        k += 8 * n
    return out


def material_record(payload: bytes, bid) -> bytes | None:
    return next((r for r in _records(payload, bid) if struct.unpack_from("<H", r, 2)[0] == 1 and len(r) >= 16),
                None)


def decode_material(rec: bytes) -> dict:
    flag, code = rec[4], chr(rec[5])
    a, b, c, d = struct.unpack_from("<4H", rec, 6)
    return {"production": flag == 0xFF, "material": code.strip() or None, "total": a, "mirrored": b,
            "unknown": c, "prod_word": d, "name": rec[16:].split(b"\x00")[0].decode("latin-1")}


_PROD = re.compile(r"(?:  x ([A-Z]) (\d\d) (\d\d) | {12})(?=ID=)")


def write_mdl(template_path: str, project, out_path: str) -> dict:
    """Write the material / production / copies of the parts of ``project`` into a copy of the GRAFIS MDL
    ``template_path`` (the MDL this session was read from)."""
    if any(p.model for p in project.pieces):
        raise MdlWriteError("an MDL holds one model; this session contains several models")
    data = Path(template_path).read_bytes()
    cont = read_container(template_path)
    if cont.errors:
        raise MdlWriteError("template: " + "; ".join(cont.errors))
    blocks = cont.by_id()
    tb = blocks.get((2, 1, 0, 0))
    if tb is None:
        raise MdlWriteError("the template has no text block")
    ts = parse_text(tb.payload)
    if "SBINFO" in ts.sections:
        raise MdlWriteError("the template is a marker file (SCB), not a model file (MDL)")
    tlist = {e.number: e for e in ts.tlist}
    # pattern record of every material in the file (unknown field + name come from it)
    patterns: dict[str, bytes] = {}
    for e in ts.tlist:
        b = blocks.get((3, e.number) + MAT_BLOCK)
        rec = material_record(b.payload, b.bid) if b is not None else None
        if rec is not None:
            patterns.setdefault(chr(rec[5]).strip(), rec)
    co = project.cut_order
    text = tb.payload.rstrip(b"\x00").decode(ENC)
    lines = text.split("\r\n")
    new_payloads, changed = {}, []
    for pc in project.pieces:
        e = tlist.get(pc.number)
        if e is None or e.name.strip() != pc.name.strip():
            raise MdlWriteError(f"part {pc.number} {pc.name!r} is not in the template MDL's part list")
        n, m = co.piece_counts.get(pc.uid, (0, 0))
        prod = bool(n or m)
        mat = (pc.material or "").strip().upper() or None
        if prod and mat is None:
            raise MdlWriteError(f"part {pc.number} {pc.name}: a part that is produced needs a material")
        if n > 99 or m > 99:
            raise MdlWriteError(f"part {pc.number} {pc.name}: more than 99 copies")
        bid = (3, pc.number) + MAT_BLOCK
        b = blocks.get(bid)
        if b is None:
            raise MdlWriteError(f"part {pc.number} {pc.name}: block {bid} missing in the template")
        recs = _records(b.payload, bid)
        own = material_record(b.payload, bid)
        old = decode_material(own) if own is not None else {"production": False, "material": None}
        if prod == old["production"] and mat == old["material"] and \
                (not prod or (old["total"], old["mirrored"]) == (n + m, m)):
            continue                                       # nothing to change for this part
        pat = own if own is not None and old["material"] == mat else patterns.get(mat or "")
        if pat is None:
            raise MdlWriteError(f"part {pc.number} {pc.name}: material {mat or '(none)'!r} is not used by any "
                                f"part of this MDL, so its GRAFIS record is not known")
        rec = bytearray(pat)
        rec[4] = 0xFF if prod else 0x00
        if prod:
            struct.pack_into("<2H", rec, 6, n + m, m)
        elif own is not None:                              # not produced: keep the part's own copy numbers
            rec[6:10] = own[6:10]
        struct.pack_into("<H", rec, 12, 1 if prod else 0)
        rest = b.payload[sum(len(r) for r in recs):]       # zero padding after the records
        k = next((i for i, r in enumerate(recs) if r == own), None) if own is not None else None
        recs = recs[:k] + [bytes(rec)] + recs[k + 1:] if k is not None else recs + [bytes(rec)]
        new_payloads[bid] = b"".join(recs) + rest
        # #TLIST line
        idx = next((i for i, ln in enumerate(lines) if ln == e.raw), None)
        if idx is None or not _PROD.search(lines[idx]):
            raise MdlWriteError(f"part {pc.number} {pc.name}: #TLIST line in an unknown layout")
        col = f"  x {mat} {n:02d} {m:02d} " if prod else " " * 12
        lines[idx] = _PROD.sub(col, lines[idx], count=1)
        changed.append(pc.number)
    new_text = "\r\n".join(lines)
    if new_text != text:
        new_payloads[(2, 1, 0, 0)] = new_text.encode(ENC) + b"\x00"
    out = rebuild_container(data, cont, new_payloads, MdlWriteError)
    write_atomic(out_path, out)
    return {"parts_changed": changed, "bytes": len(out)}
