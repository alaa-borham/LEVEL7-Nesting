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
