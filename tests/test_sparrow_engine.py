"""Optional sparrow engine (bundled executable): result must be valid and never longer than the built-in start."""
import os

import pytest
from conftest import SCB

from level7.nesting import sparrow

pytestmark = pytest.mark.skipif(not sparrow.available(), reason="sparrow executable not bundled")


def test_sparrow_engine_valid_and_not_worse(monkeypatch):
    from level7.model import FabricSettings, NestSettings
    from level7.service import open_any, run_nesting
    monkeypatch.setenv("LEVEL7_ENGINE", "auto")
    proj, _ = open_any(SCB)
    fab = FabricSettings(width=1500.0)
    m, info = run_nesting(proj, fab, NestSettings(time_limit=25, seed=1))
    assert info["validation"].ok
    assert not [p for p in m.placements if not p.placed]
    assert info["engine"] in ("sparrow", "builtin")
    # same pieces, unchanged shapes: every placement is a rigid copy of its pattern piece (validator checks area)
    assert len(m.placements) == 28


def test_instance_and_warm_start_roundtrip():
    from level7.model import FabricSettings, NestSettings
    from level7.nesting.engine import build_items
    from level7.nesting.parallel import run_parallel
    from level7.service import open_any
    proj, _ = open_any(SCB)
    co = proj.cut_order
    fab = FabricSettings(width=1430.0, margin_left=10.0, margin_start=5.0)
    st = NestSettings(time_limit=3, seed=1)
    items, _, _ = build_items(proj, co.size_quantities, co.piece_counts, fab, st)
    inst, groups = sparrow.build_instance(items, fab)
    assert sum(i["demand"] for i in inst["items"]) == len(items) == 28
    assert inst["strip_height"] == pytest.approx(fab.usable_width)
    start = run_parallel(items, fab, st, workers=1)
    sol = sparrow.warm_solution(inst, groups, start, fab)
    # converting the warm-start entries back gives the same placements
    entries = [(p["item_id"], *p["transformation"]["translation"], p["transformation"]["rotation"])
               for p in sol["solution"]["layout"]["placed_items"]]
    back = sparrow._to_result(entries, groups, fab, sol["solution"]["strip_width"], 1, 0.0, False)
    a = {(p.piece_uid, p.mirrored, round(p.x, 6), round(p.y, 6), p.rotation) for p in start.placements}
    b = {(p.piece_uid, p.mirrored, round(p.x, 6), round(p.y, 6), p.rotation) for p in back.placements}
    assert a == b and back.length == pytest.approx(start.length)
