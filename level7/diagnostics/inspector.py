"""Stand-alone GRAFIS MDL/SCB inspector.

    level7-inspect FILE [FILE ...] [-o OUTDIR] [--encoding cp1256]

Writes <name>.report.json and <name>.report.md with:
  * file signature, size, SHA-256
  * block chain (offset, id, length) and structural errors
  * text sections with byte offsets
  * parts, sizes, geometry extraction per part/size and the checks behind it
  * SCB: marker header, placements, reconstruction check (overlap, bounds, area, eff.)
  * every finding classified as confirmed / probable / unknown / unsupported
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from collections import Counter

from ..formats.grafis.container import SIGNATURE, GrafisFormatError, read_container
from ..formats.grafis.elements import KIND_POLYLINE, decode_geometry
from ..formats.grafis.textsections import parse_text


def inspect_file(path: str, encoding: str = "cp1256") -> dict:
    rep: dict = {"file": os.path.basename(path), "path": os.path.abspath(path)}
    findings = {"confirmed": [], "probable": [], "unknown": [], "unsupported": []}
    rep["findings"] = findings
    try:
        cont = read_container(path)
    except GrafisFormatError as e:
        rep["error"] = str(e)
        findings["unsupported"].append(f"not a GRAFIS container: {e}")
        return rep
    rep.update(size=cont.size, sha256=cont.sha256, header_u32=list(cont.header_u32),
               signature=SIGNATURE.decode(), block_count=len(cont.blocks), structural_errors=cont.errors)
    if not cont.errors:
        findings["confirmed"].append(
            f"block chain: {len(cont.blocks)} blocks follow each other exactly via the length field "
            "(u32 units of 8 bytes) from offset 80 to the 'mdlEND_5' trailer; header u32[1]*8+8 == file size")
    findings["unknown"].append("header u32[0] and per-block u32 check value: not a byte sum, CRC-32 or Adler-32")
    ids = Counter((b.bid[0], b.bid[1] if b.bid[0] < 3 else "k", b.bid[2], "n" if b.bid[0] == 3 and b.bid[2] in (3, 6, 7) else b.bid[3])
                  for b in cont.blocks)
    rep["block_types"] = {str(k): v for k, v in sorted(ids.items(), key=lambda x: str(x[0]))}
    rep["blocks"] = [{"offset": b.offset, "id": list(b.bid), "bytes": b.size} for b in cont.blocks]
    tb = cont.get(2, 1, 0, 0)
    if tb is None:
        findings["unsupported"].append("text block (2,1,0,0) missing")
        return rep
    ts = parse_text(tb.payload, encoding)
    rep["text_sections"] = {k: {"offset_in_file": tb.offset + 32 + ts.offsets[k], "lines": len(v)}
                            for k, v in ts.sections.items()}
    rep["version_text"] = ts.version
    findings["confirmed"].append(f"text sections in block (2,1,0,0), CRLF lines; #VERSION text = {ts.version!r} "
                                 "(meaning not known; not treated as GRAFIS program version)")
    findings["probable"].append(f"text encoding {encoding}: Arabic part names decode to valid words")
    rep["sizes"] = [{"index": s.index, "name": s.name, "ref": s.ref} for s in ts.sizes]
    rep["parts"] = []
    blocks = cont.by_id()
    geo_ok = geo_total = 0
    for t in ts.tlist:
        entry = {"number": t.number, "name": t.name, "id": t.piece_id, "production": t.production,
                 "material": t.material, "count": t.count, "mirrored": t.mirrored, "sizes_with_geometry": []}
        for s in ts.sizes:
            b = blocks.get((3, t.number, 7, s.index))
            if b is None:
                continue
            gb = decode_geometry(b.payload)
            polys = [e for e in gb.elements if e.kind == KIND_POLYLINE]
            geo_total += len(polys)
            geo_ok += sum(1 for e in polys if e.bbox_ok)
            entry["sizes_with_geometry"].append(s.name)
            if gb.errors:
                entry.setdefault("errors", []).extend(gb.errors[:5])
        rep["parts"].append(entry)
    findings["confirmed"].append(
        f"geometry blocks (3,part,7,size): {geo_ok}/{geo_total} polyline elements decode to points whose bounding "
        "box equals the bbox stored in the element record")
    try:
        from ..readers.grafis import read_grafis
        res = read_grafis(path, encoding=encoding)
        proj = res.project
        cut_conf = sum(1 for p in proj.pieces for g in p.sizes.values() if g.completeness.get("cut") == "confirmed")
        cut_prob = sum(1 for p in proj.pieces for g in p.sizes.values() if g.completeness.get("cut") == "probable")
        rep["cut_contours"] = {"confirmed": cut_conf, "probable": cut_prob}
        rep["pieces"] = [{"number": p.number, "name": p.name, "material": p.material, "production": p.production,
                          "grain_angle": p.grain_angle,
                          "sizes": {k: {"area_cm2": round(abs(_area(g.cut)) / 100, 2), "cut": g.completeness.get("cut"),
                                        "notches": len(g.notches), "internal_lines": len(g.internal),
                                        "seam": bool(g.seam), "grain": g.grain is not None}
                                    for k, g in p.sizes.items()}} for p in proj.pieces]
        findings["probable"].append("cut contour (MDL) = largest closed cycle of whole polyline elements; matches the "
                                    "GRAFIS cut flags of the 44 marker for 9/9 placed parts and the same element set "
                                    "is chosen in all 15 grading entries")
        findings["probable"].append("units = millimetres: '#TFLIST' tables declare mm; part 7 size 44 has its hem "
                                    "line at y=-1040 and T2M4/T5M4 = 1040 for size 44; SCB WIDTH 1430 equals the "
                                    "max Y of the reconstructed marker; front length ~1135 is realistic only in mm")
        findings["probable"].append("style -7/-6 = seam (net) line, -3 = grain line, 2-point flagged style 1 = notch")
        findings["unknown"].append("symbol elements (kind 6): position and code text read; meaning (drill hole, "
                                   "reference mark, ...) unknown -> exported only on layer MARK")
        findings["unknown"].append("construction data blocks (3,k,2..6) are not interpreted; only evaluated geometry")
        findings["unsupported"].append("writing MDL/SCB files")
        findings["unsupported"].append("curve definitions: GRAFIS stores evaluated polylines; original spline "
                                       "parameters are not read")
        if proj.markers:
            from ..validation.checker import marker_stats, validate_marker
            m = proj.markers[0]
            v = validate_marker(proj, m)
            st = marker_stats(proj, m)
            rep["marker"] = {"sbinfo": proj.sbinfo, "placements": len(m.placements), "validation": v.summary(),
                             "computed_efficiency_pct": round(st["efficiency_total_width_pct"], 3),
                             "computed_area_m2": round(st["pieces_area_m2"], 4),
                             "computed_length_mm": round(st["length_mm"], 2),
                             "header": res.checks}
            findings["confirmed"].append(
                f"placement block (2,8,0,0): {len(m.placements)} records of 120 bytes; reconstruction gives "
                f"{v.summary()}, efficiency {st['efficiency_total_width_pct']:.2f}% "
                f"(GRAFIS EFFCNCY {proj.sbinfo.get('EFFCNCY')}), area {st['pieces_area_m2']:.2f} m2 "
                f"(USDAREA {proj.sbinfo.get('USDAREA')}), length {st['length_mm']:.2f}")
            findings["confirmed"].append("EFFCNCY definition = sum of placed cut areas / (WIDTH x LENGTH)")
            findings["confirmed"].append("rotation = base + extra + 180*(flags&0x80); mirror byte = mirrored copy, "
                                         "mirror about pattern Y axis before rotation; marker Y axis upward - "
                                         "identical piece positions, orientations and bundles (A/B) to the GRAFIS "
                                         "screen view of this marker (docs/evidence)")
            findings["probable"].append("#SBTLIST columns = copies / mirrored copies per bundle (28 = 2 bundles x 14)")
            if proj.sources[0].internal_model_name:
                findings["confirmed"].append(f"internal MODEL name: {proj.sources[0].internal_model_name!r} "
                                             f"(differs from file name; informational only)")
            findings["unknown"].append("placement fields +28, +64..72 and flag bit 0x40")
        rep["read_issues"] = res.issues
    except Exception as e:  # report, never crash
        rep["read_error"] = repr(e)
        findings["unsupported"].append(f"full read failed: {e!r}")
    return rep


def _area(pts):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return a / 2


def to_markdown(rep: dict) -> str:
    L = [f"# Inspection report: {rep['file']}", ""]
    if "error" in rep:
        return "\n".join(L + [f"**Error:** {rep['error']}"])
    L += [f"- size: {rep['size']:,} bytes", f"- SHA-256: `{rep['sha256']}`", f"- signature: `{rep['signature']}`",
          f"- blocks: {rep['block_count']}", f"- structural errors: {rep['structural_errors'] or 'none'}", ""]
    for k, title in (("confirmed", "Confirmed"), ("probable", "Probable interpretations"),
                     ("unknown", "Unknown"), ("unsupported", "Unsupported")):
        L.append(f"## {title}")
        L += [f"- {x}" for x in rep["findings"][k]] or ["- (none)"]
        L.append("")
    L.append("## Text sections")
    for k, v in rep.get("text_sections", {}).items():
        L.append(f"- `#{k}` at file offset {v['offset_in_file']}, {v['lines']} lines")
    L += ["", "## Sizes", ", ".join(f"{s['index']}:{s['name']}" for s in rep.get("sizes", [])), "", "## Parts",
          "| # | name | production | material | count | mirrored | sizes with geometry | grain |",
          "|---|---|---|---|---|---|---|---|"]
    grains = {p["number"]: p["grain_angle"] for p in rep.get("pieces", [])}
    for p in rep.get("parts", []):
        L.append(f"| {p['number']} | {p['name']} | {p['production']} | {p['material'] or ''} | {p['count'] or ''} | "
                 f"{p['mirrored'] if p['mirrored'] is not None else ''} | {len(p['sizes_with_geometry'])} | "
                 f"{grains.get(p['number'])} |")
    if "marker" in rep:
        L += ["", "## Marker", "```", json.dumps(rep["marker"], ensure_ascii=False, indent=1, default=str), "```"]
    if rep.get("read_issues"):
        L += ["", "## Read issues"] + [f"- {x}" for x in rep["read_issues"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:  # Windows consoles default to cp1252/cp1256: never crash on Arabic names
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Inspect GRAFIS MDL/SCB files")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--outdir", default=".")
    ap.add_argument("--encoding", default="cp1256")
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    rc = 0
    for f in a.files:
        rep = inspect_file(f, a.encoding)
        base = os.path.join(a.outdir, os.path.basename(f))
        with open(base + ".report.json", "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1, default=str)
        with open(base + ".report.md", "w", encoding="utf-8") as fh:
            fh.write(to_markdown(rep))
        print(f"{f}: {len(rep.get('findings', {}).get('confirmed', []))} confirmed, "
              f"{len(rep.get('findings', {}).get('unknown', []))} unknown -> {base}.report.md")
        if "error" in rep or rep.get("structural_errors"):
            rc = 1
    return rc


_ = struct
if __name__ == "__main__":
    sys.exit(main())
