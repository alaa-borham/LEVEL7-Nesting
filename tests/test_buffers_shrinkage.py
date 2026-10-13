"""Directional buffers (X / Y) between pieces and shrinkage (length / width %)."""
from dataclasses import replace

from conftest import SCB
from shapely.geometry import Polygon

from level7.geometry import grow_rect, placement_points
from level7.model import FabricSettings, Marker, NestSettings
from level7.service import open_any, run_nesting
from level7.validation.checker import validate_marker


def _nest(fab, engine="builtin", proj=None):
    proj = proj or open_any(SCB)[0]
    m, info = run_nesting(proj, fab, NestSettings(time_limit=4, seed=1, engine=engine), workers=1)
    return proj, m, info


def test_grow_rect_is_minkowski_with_rectangle():
    sq = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    g = grow_rect(sq, 3, 1)
    assert g.bounds == (-3, -1, 13, 11)
    assert abs(g.area - 16 * 12) < 1e-9
    tri = Polygon([(0, 0), (10, 0), (0, 10)])
    assert grow_rect(tri, 2, 2).contains(tri.buffer(1.99))        # square of half-side 2 contains the r=2 disc


def test_buffers_kept_between_pieces_and_checked():
    fab = FabricSettings(width=1500.0, buffer_x=12.0, buffer_y=5.0)
    proj, m, info = _nest(fab)
    assert info["validation"].ok, info["validation"].summary()
    # independent check on the placed contours: piece A grown by the full buffer rectangle never meets piece B
    polys = [Polygon(placement_points(proj.piece(p.piece_uid).sizes[p.size].cut, p)) for p in m.placements if p.placed]
    for i, a in enumerate(polys):
        ga = grow_rect(a.buffer(0), 12.0 - 0.05, 5.0 - 0.05)
        for b in polys[i + 1:]:
            assert ga.intersection(b).area < 0.01
    # buffers are not applied against the margins: a piece may touch the selvedge
    ys = [min(y for _, y in placement_points(proj.piece(p.piece_uid).sizes[p.size].cut, p)) for p in m.placements]
    assert min(ys) < 1.0
    # the same layout without the buffer requirement is fine; a tight layout violates the buffer
    _, tight, _ = _nest(FabricSettings(width=1500.0), proj=proj)
    rep = validate_marker(proj, Marker("t", replace(fab), tight.placements))
    assert not rep.ok and any(i.kind == "spacing" for i in rep.issues)


def test_shrinkage_scales_pieces_in_marker_axes():
    fab = FabricSettings(width=1500.0, shrink_x=4.0, shrink_y=-2.0)
    proj, m, info = _nest(fab)
    assert info["validation"].ok, info["validation"].summary()
    for p in m.placements:
        assert (p.sx, p.sy) == (1.04, 0.98)
    p = next(p for p in m.placements if p.placed)
    g = proj.piece(p.piece_uid).sizes[p.size]
    plain = Polygon(placement_points(g.cut, replace(p, sx=1.0, sy=1.0)))
    shrunk = Polygon(placement_points(g.cut, p))
    (x0, y0, x1, y1), (u0, v0, u1, v1) = plain.bounds, shrunk.bounds
    assert abs((u1 - u0) - 1.04 * (x1 - x0)) < 1e-6
    assert abs((v1 - v0) - 0.98 * (y1 - y0)) < 1e-6
    assert abs(shrunk.area - plain.area * 1.04 * 0.98) < 1e-6 * plain.area


def test_shrinkage_not_written_to_scb(tmp_path):
    import pytest

    from level7.formats.grafis.writer import ScbWriteError, write_scb
    proj, m, _ = _nest(FabricSettings(width=1500.0, shrink_x=2.0))
    with pytest.raises(ScbWriteError):
        write_scb(SCB, proj, m, str(tmp_path / "x.scb"))


def test_sparrow_gets_only_turns_that_commute_with_shrinkage():
    from level7.nesting.engine import build_items
    from level7.nesting.sparrow import build_instance
    proj, _ = open_any(SCB)
    st = NestSettings(allow_rotation_90=True)
    co = proj.cut_order
    for kw, want in ((dict(shrink_x=2.0), {0.0, 180.0}), (dict(buffer_y=4.0), {0.0, 180.0}),
                     (dict(shrink_x=2.0, shrink_y=2.0, buffer_x=3.0, buffer_y=3.0), {0.0, 90.0, 180.0, 270.0})):
        fab = FabricSettings(width=1500.0, **kw)
        items, _, _ = build_items(proj, co.size_quantities, co.piece_counts, fab, st)
        inst, _ = build_instance(items, fab)
        for it in inst["items"]:
            assert set(it["orientation"]["rotation"]["angles"]) == want


def test_sparrow_runs_with_shrinkage_and_90_degrees(monkeypatch):
    import pytest

    from level7.nesting import sparrow
    if not sparrow.available():
        pytest.skip("sparrow executable not bundled")
    monkeypatch.setenv("LEVEL7_ENGINE", "auto")
    proj, _ = open_any(SCB)
    fab = FabricSettings(width=1500.0, shrink_x=2.0, buffer_x=4.0)
    m, info = run_nesting(proj, fab, NestSettings(time_limit=15, seed=1, allow_rotation_90=True), workers=1)
    # 90° turns were allowed, so only grain warnings may remain
    assert {i.kind for i in info["validation"].issues} <= {"grain"}
    assert not [p for p in m.placements if not p.placed]
    assert info["engine"] == "sparrow"
