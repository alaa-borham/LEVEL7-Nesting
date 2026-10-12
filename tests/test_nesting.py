import copy
import threading
from collections import Counter

import pytest

from level7.geometry import bbox, placement_points, ring_area
from level7.model import FabricSettings, LayType, NestSettings
from level7.nesting.engine import NestEngine, build_items
from level7.service import run_nesting


def _copies(m):
    return Counter((pl.piece_uid, pl.size, pl.mirrored) for pl in m.placements if pl.placed)


@pytest.mark.parametrize("width", [1400, 1430, 1500])
def test_nest_widths_valid(scb, width):
    p = copy.deepcopy(scb.project)
    marker, info = run_nesting(p, FabricSettings(width=width), NestSettings(time_limit=6, seed=3), workers=2)
    v = info["validation"]
    assert v.ok, [i.message for i in v.issues][:5]
    assert sum(1 for pl in marker.placements if pl.placed) == 28
    assert _copies(marker) == _copies(p.markers[0])
    # geometry unchanged: every placed contour has the original area
    for pl in marker.placements:
        g = p.piece(pl.piece_uid).sizes[pl.size]
        assert abs(ring_area(placement_points(g.cut, pl))) == pytest.approx(abs(ring_area(g.cut)), rel=1e-9)
        b = bbox(placement_points(g.cut, pl))
        assert b[1] >= -0.02 and b[3] <= width + 0.02


def test_spacing_and_margins_respected(scb):
    p = copy.deepcopy(scb.project)
    fab = FabricSettings(width=1500, spacing=5.0, margin_left=10, margin_right=10, margin_start=20, margin_end=20)
    marker, info = run_nesting(p, fab, NestSettings(time_limit=4, seed=1), workers=1)
    assert info["validation"].ok, [i.message for i in info["validation"].issues][:5]


def test_piece_too_wide_is_reported_not_scaled(scb):
    p = copy.deepcopy(scb.project)
    marker, info = run_nesting(p, FabricSettings(width=300), NestSettings(time_limit=2, seed=1), workers=1)
    unplaced = [pl for pl in marker.placements if not pl.placed]
    assert unplaced and all("usable width" in pl.reason for pl in unplaced)
    assert info["validation"].ok


def test_pinned_piece_stays(scb):
    p = copy.deepcopy(scb.project)
    pin = copy.copy(p.markers[0].placements[0])
    pin.pinned = True
    marker, info = run_nesting(p, FabricSettings(width=1430), NestSettings(time_limit=3, seed=1), pinned=[pin],
                               workers=1)
    same = [pl for pl in marker.placements if pl.uid == pin.uid]
    assert len(same) == 1 and same[0].x == pytest.approx(pin.x, abs=0.011) and same[0].y == pytest.approx(pin.y, abs=0.011)
    assert info["validation"].ok


def test_stop_keeps_best_valid(scb):
    p = scb.project
    fab, st = FabricSettings(width=1430), NestSettings(time_limit=60, seed=1)
    items, _, _ = build_items(p, p.cut_order.size_quantities, p.cut_order.piece_counts, fab, st)
    ev = threading.Event()
    timer = threading.Timer(2.5, ev.set)
    timer.start()
    res = NestEngine(items, fab, st, stop_event=ev).run()
    assert res.stopped and len(res.placements) == 28 and res.elapsed < 30


def test_seed_reproducible(scb):
    p = scb.project
    fab = FabricSettings(width=1430)
    out = []
    for _ in range(2):
        st = NestSettings(time_limit=120, seed=7, attempts=25)
        items, _, _ = build_items(p, p.cut_order.size_quantities, p.cut_order.piece_counts, fab, st)
        r = NestEngine(items, fab, st).run()
        out.append([(pl.piece_uid, round(pl.x, 3), round(pl.y, 3), pl.rotation) for pl in r.placements])
    assert out[0] == out[1]


def test_face_to_face_lay_pairs(scb):
    p = copy.deepcopy(scb.project)
    fab = FabricSettings(width=1430, lay_type=LayType.FACE_TO_FACE)
    marker, info = run_nesting(p, fab, NestSettings(time_limit=2, seed=1), workers=1)
    assert info["validation"].ok
    assert all(not pl.mirrored for pl in marker.placements)
    assert any("produces" in w for w in info["warnings"])  # 1+0 parts get an extra mirrored copy -> warned


def test_lay_direction_marks_180_turned_copies():
    from level7.geometry import lay_direction
    from level7.model import NestSettings, Piece, Placement
    from level7.nesting.engine import grain_rotations
    for ga in (0.0, 12.5, 170.0):
        base = (-ga) % 360.0
        assert lay_direction(ga, Placement("a", "p", "44", rotation=base)) == 1
        assert lay_direction(ga, Placement("a", "p", "44", rotation=(base + 180) % 360)) == -1
        mb = (ga - 180.0) % 360.0                       # base rotation of a mirrored copy
        piece = Piece(uid="p", source_id="", number=1, name="x", grain_angle=ga)
        assert grain_rotations(piece, True, NestSettings(allow_rotation_180=False))[0] == [round(mb, 6) % 360.0]
        assert lay_direction(ga, Placement("a", "p", "44", rotation=mb, mirrored=True)) == 1
        assert lay_direction(ga, Placement("a", "p", "44", rotation=(mb + 180) % 360, mirrored=True)) == -1
    assert lay_direction(None, Placement("a", "p", "44")) is None
