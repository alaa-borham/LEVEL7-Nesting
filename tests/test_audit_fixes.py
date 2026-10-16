"""Regressions from the production audit: folded-lay efficiency, permitted 90 deg turns, batch / input checks."""
import copy

import pytest
from conftest import SCB

from level7.geometry import bbox, placement_points
from level7.model import LayType, Marker, Placement
from level7.service import open_any
from level7.validation.checker import marker_stats, validate_marker


def test_folded_lay_counts_both_halves():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    folded = copy.deepcopy(m)
    folded.fabric.lay_type = LayType.FOLDED
    a, b = marker_stats(proj, m), marker_stats(proj, folded)
    assert abs(b["efficiency_total_width_pct"] - 2 * a["efficiency_total_width_pct"]) < 1e-6
    assert b["efficiency_total_width_pct"] <= 100.0 + 1e-6 or a["efficiency_total_width_pct"] > 50


def test_turn_of_90_degrees_valid_only_when_allowed():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    pc = next(p for p in proj.pieces if any(g.grain is not None for g in p.sizes.values()))
    size = next(s for s, g in pc.sizes.items() if g.grain is not None)
    aligned = next(q.rotation for q in m.placements if q.piece_uid == pc.uid)       # grain along the length
    pl = Placement("t", pc.uid, size, rotation=(aligned + 90.0) % 360)
    b = bbox(placement_points(pc.sizes[size].cut, pl))
    pl.x, pl.y = 10 - b[0], 10 - b[1]
    mk = Marker("t", copy.deepcopy(m.fabric), [pl])
    mk.fabric.width = max(mk.fabric.width, b[3] - b[1] + 40)
    straight = [aligned, (aligned + 180.0) % 360]
    bad = validate_marker(proj, mk, allowed_rotations={(pc.uid, False): straight})
    assert any(i.kind == "grain" for i in bad.issues)
    ok = validate_marker(proj, mk, allowed_rotations={(pc.uid, False): [0.0, 90.0, 180.0, 270.0]})
    assert not any(i.kind == "grain" for i in ok.issues)


def test_run_nesting_refuses_impossible_inputs():
    from level7.model import FabricSettings, NestSettings
    from level7.service import run_nesting
    proj, _ = open_any(SCB)
    with pytest.raises(ValueError, match="width"):
        run_nesting(proj, FabricSettings(width=0.0), NestSettings(time_limit=1))
    with pytest.raises(ValueError, match="shrinkage"):
        run_nesting(proj, FabricSettings(width=1500.0, shrink_x=-100.0), NestSettings(time_limit=1))


def test_batch_rejects_bad_rows(tmp_path):
    from level7.batch import OrderError, parse_orders
    p = tmp_path / "o.csv"
    p.write_text("marker,file,size,qty,width\nM1,x.mdl,44,1,-10\n", encoding="utf-8")
    with pytest.raises(OrderError, match="width"):
        parse_orders(str(p))
    p.write_text("marker,file,size,qty,width\nM1,x.mdl,44,-2,1500\n", encoding="utf-8")
    with pytest.raises(OrderError, match="negative"):
        parse_orders(str(p))


def test_aama_in_inches_is_converted(tmp_path):
    import os
    import shutil

    from conftest import SAMPLES

    from level7.readers.aama import read_aama
    src = os.path.join(SAMPLES, "reference", "aama", "Neay_blue_pants")
    shutil.copy(src + ".dxf", tmp_path / "x.dxf")
    rul = open(src + ".rul", encoding="latin-1").read()
    (tmp_path / "x.rul").write_text(rul.replace("UNITS:METRIC", "UNITS:ENGLISH"), encoding="latin-1")
    a, _ = read_aama(src + ".dxf")
    b, issues = read_aama(str(tmp_path / "x.dxf"))
    s = next(iter(a.pieces[0].sizes))
    pa, pb = a.pieces[0].sizes[s].cut[1], b.pieces[0].sizes[s].cut[1]
    assert abs(pb[0] - 25.4 * pa[0]) < 1e-6 and abs(pb[1] - 25.4 * pa[1]) < 1e-6
    assert any("inch" in i for i in issues)


def test_iso_cuts_a_hole_before_its_piece():
    from level7.exporters.iso import _band_order

    class P:
        def __init__(self, pts):
            self.points = pts
    outer = P([(0, 0), (100, 0), (100, 100), (0, 100)])
    hole = P([(40, 40), (60, 40), (60, 60), (40, 60)])
    other = P([(200, 0), (300, 0), (300, 50), (200, 50)])
    assert _band_order([outer, other, hole], 400) == [hole, outer, other]


def test_update_redirects_stay_on_https_and_github():
    from level7.updater import _redirect_ok
    hosts = ("github.com", "api.github.com")
    assert _redirect_ok("https://objects.githubusercontent.com/a", hosts)
    assert not _redirect_ok("http://objects.githubusercontent.com/a", hosts)
    assert not _redirect_ok("https://githubusercontent.com.evil.example/a", hosts)


def test_marker_area_matches_a_full_union():
    from shapely.ops import unary_union

    from level7.validation.checker import placed_polygons
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    u = unary_union(list(placed_polygons(proj, m).values())).area
    assert abs(marker_stats(proj, m)["pieces_area_m2"] * 1e6 - u) < 1e-3


def test_rotated_labels_get_a_direction(tmp_path):
    from level7.service import export_marker
    proj, _ = open_any(SCB)
    p = tmp_path / "l.plt"
    export_marker(proj, proj.markers[0], "plt", str(p))
    t = p.read_text()
    assert t.count("DI") % 2 == 0 and "LB" in t
