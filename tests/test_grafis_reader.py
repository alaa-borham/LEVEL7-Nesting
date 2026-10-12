import math
import struct

import pytest
from conftest import MDL, SCB

from level7.formats.grafis.container import GrafisFormatError, parse_container, read_container
from level7.formats.grafis.elements import KIND_POLYLINE, decode_geometry
from level7.geometry import bbox, ring_area


def test_container_chain_exact():
    for path, size, n, sha in ((MDL, 2003864, 558, "0b729b223c72caa8685734b430c83e35009b1b4d151cacaa343edf8b8a78fc51"),
                               (SCB, 1097872, 445, "a96d5513c6c1349154105cfc63108774b987168712db74e5723b84d51d2d0f4c")):
        c = read_container(path)
        assert c.ok, c.errors
        assert c.size == size and len(c.blocks) == n and c.sha256 == sha
        assert c.header_u32[1] * 8 + 8 == size
        assert all(b.offset + b.size == nb.offset for b, nb in zip(c.blocks, c.blocks[1:]))


def test_damaged_files_are_diagnosed_not_crashing():
    data = open(SCB, "rb").read()
    with pytest.raises(GrafisFormatError):
        parse_container(b"not a grafis file" * 10)
    trunc = parse_container(data[:500000])
    assert not trunc.ok and trunc.blocks
    broken = bytearray(data)
    off = read_container(SCB).blocks[50].offset
    broken[off + 8:off + 16] = b"XXXXXXXX"
    c = parse_container(bytes(broken))
    assert not c.ok and len(c.blocks) == 50
    bad_len = bytearray(data)
    struct.pack_into("<I", bad_len, off + 4, 10 ** 8)
    assert not parse_container(bytes(bad_len)).ok
    # geometry block with corrupted record count -> error list, no exception
    g = bytearray(read_container(SCB).get(3, 7, 7, 10).payload)
    struct.pack_into("<I", g, 0, 10 ** 6)
    assert decode_geometry(bytes(g)).errors


def test_scb_text_sections(scb):
    sb = scb.text.sbinfo
    assert sb["WIDTH"] == "1430" and sb["LENGTH"] == "2930" and sb["EFFCNCY"] == "83.86"
    assert sb["USDAREA"] == "3.51" and sb["PIECES"] == "9" and sb["BUNDLES"] == "2"
    assert sb["PCSTOTAL"] == "28" and sb["PCSUNPLC"] == "0"
    assert sb["MODEL"] == "PANTS Black.mdl" and sb["MATERIALO"] == "upper fabric"
    assert scb.text.sbgrlst == [(1, "44"), (2, "44")]
    names = [e.name for e in scb.text.sbtlist]
    assert names == ["front", "back", "ورقه جيب الصدر", "pants wist+4-5", "pants wist+10", "ziper LT", "ziper RT",
                     "فلتات الجيب الخلف", "plit wist"]
    assert scb.text.version == "1000"


def test_mdl_sizes_parts(mdl, scb):
    ts = mdl.text
    assert [s.name for s in ts.sizes[1:]] == [str(x) for x in range(28, 56, 2)]
    assert ts.sizes[1].ref == "__HN40_0" and ts.sizes[-1].ref == "__HN53_0"
    assert len(ts.tlist) == 19
    ids_mdl = {e.piece_id for e in ts.tlist}
    ids_scb = {e.piece_id for e in scb.text.tlist}
    assert len(ids_mdl & ids_scb) == 19
    prod = [e.number for e in ts.tlist if e.production]
    assert prod == [7, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19]
    assert {e.number: e.material for e in ts.tlist if e.production}[10] == "F"
    assert len(ts.measure_tables) == 11


def test_all_polyline_points_match_stored_bbox():
    for path in (MDL, SCB):
        c = read_container(path)
        n = 0
        for b in c.blocks:
            if b.bid[0] == 3 and b.bid[2] == 7:
                g = decode_geometry(b.payload)
                assert not g.errors, (b.bid, g.errors)
                for e in g.elements:
                    if e.kind == KIND_POLYLINE:
                        assert e.bbox_ok
                        n += 1
        assert n == 4155


def test_mdl_cut_contour_equals_grafis_cut_flags(mdl, scb):
    """MDL contour reconstruction (outer cycle) == SCB GRAFIS cut flags for every placed part (size 44)."""
    m = {p.number: p for p in mdl.project.pieces}
    s = {p.number: p for p in scb.project.pieces}
    for num in (7, 9, 11, 12, 13, 14, 15, 17, 18):
        gm, gs = m[num].sizes["44"], s[num].sizes["44"]
        assert gs.completeness["cut"] == "confirmed"
        assert gm.completeness["cut"] == "probable"
        assert len(gm.cut) == len(gs.cut)
        assert abs(abs(ring_area(gm.cut)) - abs(ring_area(gs.cut))) < 1e-6
        assert bbox(gm.cut) == pytest.approx(bbox(gs.cut), abs=1e-6)


def test_every_size_has_distinct_graded_geometry(mdl):
    front = next(p for p in mdl.project.pieces if p.number == 7)
    areas = [abs(ring_area(front.sizes[s].cut)) for s in mdl.project.size_names]
    assert all(b > a for a, b in zip(areas, areas[1:]))          # grows with size
    w = [bbox(front.sizes[s].cut)[2] - bbox(front.sizes[s].cut)[0] for s in mdl.project.size_names]
    h = [bbox(front.sizes[s].cut)[3] - bbox(front.sizes[s].cut)[1] for s in mdl.project.size_names]
    # not a uniform scaling: width and height ratios differ
    assert abs(w[-1] / w[0] - h[-1] / h[0]) > 0.05


def test_grain_read_for_production_pieces(mdl):
    for p in mdl.project.pieces:
        if p.production:
            assert p.grain_angle is not None
            assert p.grain_angle in (0.0, 90.0)


def test_units_millimetres_evidence(mdl):
    # hem line of the front (size 44) lies at y = -1040 = T5M4 / T2M4 for size 44 in #TFLIST (mm)
    front = next(p for p in mdl.project.pieces if p.number == 7)
    ys = {round(pt[1], 3) for line in front.sizes["44"].internal for pt in line.points}
    assert -1040.0 in ys
    t2 = next(t for t in mdl.text.measure_tables if t.part == 2)
    d = next(r for r in t2.rows if r[0] == "T2M4")
    assert d[1] == "mm" and d[3][9] == "1040"
    _ = math


def test_symbols_are_measurement_annotations_not_drill_holes():
    import re
    from level7.readers.grafis import read_grafis
    proj = read_grafis(MDL).project
    ms = [m.text for p in proj.pieces for g in p.sizes.values() for m in g.measures]
    assert len(ms) == 615
    assert all(re.fullmatch(r"([A-Z]=)?\d+(\.\d+)?( \(\d+\*\))?", t) for t in ms)
    # measures are never turned into drill holes
    assert all(not g.drills for p in proj.pieces for g in p.sizes.values())


def test_size_referencing_base_uses_base_geometry(monkeypatch):
    """GRAFIS may store only the base block for the size whose GRDTAB ref is the base entry (user model 52-S)."""
    import level7.readers.grafis as rg
    orig = rg.read_container

    def without_size_28(path):
        c = orig(path)
        c.blocks = [b for b in c.blocks if not (b.bid[0] == 3 and b.bid[2] == 7 and b.bid[3] == 2)]
        return c
    full = rg.read_grafis(MDL).project
    monkeypatch.setattr(rg, "read_container", without_size_28)
    proj = rg.read_grafis(MDL).project
    for a, b in zip(full.pieces, proj.pieces):
        if "28" in a.sizes:
            assert "28" in b.sizes                                 # size 28 -> ref __HN40_0 = base
            assert b.sizes["28"].cut == a.sizes["base:__HN40_0"].cut
            assert any("GRDTAB reference" in n for n in b.notes)
