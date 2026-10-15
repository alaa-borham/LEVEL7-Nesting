"""Opening a PLT / HP-GL marker: pieces rebuilt from the plotted outlines."""
import os

from conftest import SAMPLES
from shapely.geometry import Polygon

from level7.geometry import placement_points
from level7.readers.plt import read_strokes
from level7.service import export_marker, open_any
from level7.validation.checker import validate_marker

REF = os.path.join(SAMPLES, "reference", "Neay blue pants-44-1500.plt")
SCB1500 = os.path.join(SAMPLES, "Neay blue pants-44-1500.scb")


def _areas(proj, marker):
    return sorted(round(Polygon(placement_points(proj.piece(p.piece_uid).sizes[p.size].cut, p)).area / 100)
                  for p in marker.placements if p.placed)


def test_grafis_plt_gives_the_scb_marker():
    proj, issues = open_any(REF)
    m = proj.markers[0]
    scb, _ = open_any(SCB1500)
    sm = scb.markers[0]
    assert len(m.placements) == sum(1 for p in sm.placements if p.placed) == 28
    assert m.fabric.width == 1500.0 and m.origin == "original"
    assert abs(m.length - sm.length) < 2.0
    assert validate_marker(proj, m).ok
    # same pieces (by area, 1 cm2 steps) as the SCB marker
    a, b = _areas(proj, m), _areas(scb, sm)
    assert all(abs(x - y) <= max(2, 0.01 * y) for x, y in zip(a, b))
    # copies of one shape share a part; mirrored copies are recognised
    assert len(proj.pieces) < 28
    assert any(p.mirrored for p in m.placements)
    assert sum(sum(c) for c in proj.cut_order.piece_counts.values()) == 28
    assert any(p.sizes["PLT"].notches for p in proj.pieces)


def test_own_plt_export_reads_back(tmp_path):
    scb, _ = open_any(SCB1500)
    out = str(tmp_path / "x.plt")
    export_marker(scb, scb.markers[0], "plt", out)
    proj, _ = open_any(out)
    m = proj.markers[0]
    assert len(m.placements) == sum(1 for p in scb.markers[0].placements if p.placed)
    assert validate_marker(proj, m).ok


def test_relative_moves_and_semicolons():
    s = read_strokes(b"IN;SP1;PU0,0;PD400,0,400,400;PR-400,0;PU;PA800,800;PD;PA1200,800;")
    assert s[0] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert s[1] == [(20.0, 20.0), (30.0, 20.0)]
