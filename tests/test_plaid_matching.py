"""Plaid / stripe matching: anchors on pattern lines, validation, storage, sparrow left out."""
from dataclasses import replace

from conftest import SCB

from level7 import matching
from level7.model import FabricSettings, Marker, NestSettings
from level7.service import open_any, run_nesting
from level7.validation.checker import validate_marker


def _project_with_rules(dx=0.0, dy=0.0):
    proj, _ = open_any(SCB)
    ruled = []
    for pc in proj.pieces:
        gs = list(pc.sizes.values())
        if pc.production and gs and gs[0].notches:
            pc.match = {"kind": "notch", "index": 0, "x": True, "y": True, "dx": dx, "dy": dy}
            ruled.append(pc)
    assert ruled
    return proj, ruled


def test_line_error():
    assert matching.line_error(170.0, 10.0, 80.0) == 0.0
    assert abs(matching.line_error(172.5, 10.0, 80.0) - 2.5) < 1e-9
    assert abs(matching.line_error(167.0, 10.0, 80.0) + 3.0) < 1e-9


def test_nested_anchors_on_pattern_lines():
    proj, ruled = _project_with_rules(dx=20.0, dy=-7.0)
    fab = FabricSettings(width=1500.0, repeat_x=80.0, repeat_y=60.0, repeat_offset_x=10.0, repeat_offset_y=5.0)
    m, info = run_nesting(proj, fab, NestSettings(time_limit=5, seed=1, engine="builtin"), workers=1)
    assert info["validation"].ok, info["validation"].summary()
    assert not [p for p in m.placements if not p.placed]
    checked = 0
    for pl in m.placements:
        e = matching.placement_error(proj.piece(pl.piece_uid), pl, fab)
        if e is not None:
            assert all(abs(v) < 0.02 for v in e)
            checked += 1
    assert checked >= len(ruled)


def test_one_direction_stripes():
    proj, _ = _project_with_rules()
    for kw in (dict(repeat_x=50.0), dict(repeat_y=40.0)):
        fab = FabricSettings(width=1500.0, **kw)
        m, info = run_nesting(proj, fab, NestSettings(time_limit=4, seed=2, engine="builtin"), workers=1)
        assert info["validation"].ok, (kw, info["validation"].summary())


def test_validator_flags_unmatched_and_snap_fixes_it():
    proj, _ = _project_with_rules()
    fab = FabricSettings(width=1500.0, repeat_x=80.0, repeat_y=60.0)
    m, _ = run_nesting(proj, fab, NestSettings(time_limit=4, seed=1, engine="builtin"), workers=1)
    pl = next(p for p in m.placements if proj.piece(p.piece_uid).match)
    pl.x += 9.0
    rep = validate_marker(proj, Marker("t", fab, m.placements))
    assert any(i.kind == "match" for i in rep.issues)
    dx, dy = matching.snap(proj.piece(pl.piece_uid), pl, fab)
    assert abs(dx + 9.0) < 0.05
    # without a repeat nothing is checked
    assert not any(i.kind == "match" for i in validate_marker(proj, Marker("t", replace(fab, repeat_x=0.0,
                                                                                         repeat_y=0.0),
                                                                     m.placements)).issues)


def test_match_rules_saved_with_the_project(tmp_path):
    from level7.project_storage.store import load_project, save_project
    proj, ruled = _project_with_rules(dx=12.5)
    path = str(tmp_path / "p.l7n")
    save_project(proj, path)
    p2 = load_project(path)
    assert p2.piece(ruled[0].uid).match == ruled[0].match


def test_sparrow_not_used_for_matched_jobs(monkeypatch):
    monkeypatch.setenv("LEVEL7_ENGINE", "auto")
    proj, _ = _project_with_rules()
    fab = FabricSettings(width=1500.0, repeat_x=80.0)
    _, info = run_nesting(proj, fab, NestSettings(time_limit=4, seed=1), workers=1)
    assert info["engine"] == "builtin" and info["validation"].ok
