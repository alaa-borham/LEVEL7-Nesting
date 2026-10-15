"""Opening a PLT / HP-GL marker: pieces rebuilt from the plotted outlines."""
import os

import pytest

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
    assert any(p.sizes["44"].notches for p in proj.pieces)
    # the size is read from the "44" GRAFIS plots inside the pieces (strokes); small parts without text get it too
    assert proj.size_names == ["44"] and {p.size for p in m.placements} == {"44"}
    assert proj.cut_order.size_quantities == {"44": 1}


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


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("text", ["44", "XL", "M-53", "3XL", "S"])
def test_stroked_text_read_in_every_direction(text, rot):
    from level7.exporters.strokefont import text_strokes
    from level7.readers.plt_text import clusters, read_text
    st = [s for s in text_strokes(text, (500.0, 300.0), 12.0, rot)]
    cl = clusters(st)
    assert len(cl) == 1
    assert read_text(cl[0])[0] == text


@pytest.fixture(scope="module")
def two_sizes():
    from conftest import MDL

    from level7.model import FabricSettings, NestSettings
    from level7.service import run_nesting
    proj, _ = open_any(MDL)
    proj.cut_order.size_quantities = {"28": 1, "54": 1}
    m, _ = run_nesting(proj, FabricSettings(width=1500.0), NestSettings(time_limit=3, seed=1, engine="builtin"),
                       workers=1)
    return proj, m


@pytest.mark.parametrize("profile", ["labels", "strokes"])
def test_sizes_of_a_two_size_marker(two_sizes, profile, tmp_path):
    from level7.exporters.plt import algotex_grafis_config
    proj, m = two_sizes
    out = str(tmp_path / "x.plt")
    export_marker(proj, m, "plt", out, algotex_grafis_config() if profile == "strokes" else None)
    back, _ = open_any(out)
    bm = back.markers[0]
    assert validate_marker(back, bm).ok
    src = {}
    for pl in m.placements:
        if pl.placed:
            src.setdefault(round(Polygon(placement_points(proj.piece(pl.piece_uid).sizes[pl.size].cut, pl)).area),
                           set()).add(pl.size)
    read = [(round(Polygon(placement_points(back.piece(pl.piece_uid).sizes[pl.size].cut, pl)).area), pl.size)
            for pl in bm.placements]
    # every size read is the right one; pieces GRAFIS plots without a text keep "PLT" when the marker has 2 sizes
    assert {"28", "54"} <= set(back.size_names)
    for a, s in read:
        near = [v for k, v in src.items() if abs(k - a) <= max(5, 0.002 * a)]
        assert near and (s == "PLT" or any(s in v for v in near))
    if profile == "labels":
        assert all(s != "PLT" for _, s in read)


def test_upside_down_readings_take_the_direction_of_the_clear_texts():
    """'66' also reads '99' turned 180 deg: the direction of the other (clear) texts decides; '09' / 'SX' are not
    sizes."""
    from level7.exporters.strokefont import text_strokes
    from level7.readers.plt_text import ambiguous, candidates, choose, clusters
    for rot in (0, 90, 180, 270):
        cs = candidates(clusters(text_strokes("66", (0.0, 0.0), 12.0, rot))[0])
        assert ambiguous(cs)
        assert choose(cs, [rot])[0] == "66" and choose(cs, [(rot + 180) % 360])[0] == "99"
        assert not ambiguous(candidates(clusters(text_strokes("44", (0.0, 0.0), 12.0, rot))[0]))
        assert choose(candidates(clusters(text_strokes("60", (0.0, 0.0), 12.0, rot))[0]))[0] == "60"
        assert choose(candidates(clusters(text_strokes("XS", (0.0, 0.0), 12.0, rot))[0]))[0] == "XS"
