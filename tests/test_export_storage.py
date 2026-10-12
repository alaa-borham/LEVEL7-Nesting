import math
import os

import ezdxf
import pytest

from level7.exporters.dxf import read_dxf_paths, write_dxf
from level7.exporters.iso import MachineProfile, NotConfigured, simulate_iso, write_iso
from level7.exporters.plt import PlotterConfig, read_plt, write_plt
from level7.exporters.scene import Path, Scene, Text, marker_scene
from level7.project_storage.store import load_project, save_project


def _maxdev(a, b):
    assert len(a) == len(b)
    return max(math.dist(p, q) for p, q in zip(a, b))


def test_plt_1000mm_square_is_1to1(tmp_path):
    sq = [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]
    sc = Scene(paths=[Path("CUT", sq, True)])
    f = tmp_path / "sq.plt"
    write_plt(sc, str(f))
    raw = f.read_text()
    assert "PD40000,0,40000,40000,0,40000,0,0;" in raw
    paths, _ = read_plt(str(f))
    assert _maxdev(paths[0].points, sq + [sq[0]]) == 0.0


def test_plt_marker_roundtrip_and_tool_separation(scb, tmp_path):
    sc = marker_scene(scb.project, scb.project.markers[0])
    f = tmp_path / "m.plt"
    cfg = PlotterConfig()
    write_plt(sc, str(f), cfg)
    paths, labels = read_plt(str(f), cfg)
    cut_src = [p.points + [p.points[0]] for p in sc.paths if p.layer == "CUT"]
    cut_out = [p.points for p in paths if p.pen == cfg.pens["CUT"]]
    assert len(cut_out) == len(cut_src) == 28
    assert max(_maxdev(a, b) for a, b in zip(cut_src, cut_out)) <= math.sqrt(2) * 0.5 / cfg.units_per_mm + 1e-9  # x/y quantisation
    # seam / internal / text never on the cutting pen
    assert cfg.pens["SEAM"] != cfg.pens["CUT"] and cfg.pens["TEXT"] != cfg.pens["CUT"]
    assert len(labels) == 28 and all(pen == cfg.pens["TEXT"] for pen, _ in labels)
    n_seam = sum(1 for p in sc.paths if p.layer in ("SEAM", "INTERNAL"))
    assert sum(1 for p in paths if p.pen == cfg.pens["SEAM"]) == n_seam


def test_dxf_roundtrip_exact(scb, tmp_path):
    sc = marker_scene(scb.project, scb.project.markers[0])
    f = tmp_path / "m.dxf"
    write_dxf(sc, str(f))
    doc = ezdxf.readfile(str(f))
    assert doc.header["$INSUNITS"] == 4
    got = read_dxf_paths(str(f))
    src = [p for p in sc.paths if p.layer == "CUT"]
    assert len(got["CUT"]) == len(src)
    for p, (pts, closed) in zip(src, got["CUT"]):
        assert closed and _maxdev(p.points, pts) < 1e-9
    assert {"SEAM", "NOTCH", "GRAIN", "INTERNAL"} <= set(got)
    assert all(t.dxf.layer == "TEXT" for t in doc.modelspace().query("TEXT"))


def test_dxf_1000mm(tmp_path):
    sc = Scene(paths=[Path("CUT", [(0, 0), (1000, 0)], False)], texts=[Text("TEXT", "x", (0, 0), 5)])
    f = tmp_path / "l.dxf"
    write_dxf(sc, str(f))
    pts, _ = read_dxf_paths(str(f))["CUT"][0]
    assert math.dist(pts[0], pts[1]) == 1000.0


def test_iso_refused_without_profile_and_diagnostic_simulates(scb, tmp_path):
    sc = marker_scene(scb.project, scb.project.markers[0])
    with pytest.raises(NotConfigured):
        write_iso(sc, str(tmp_path / "x.iso"))
    f = tmp_path / "d.iso"
    st = write_iso(sc, str(f), diagnostic=True)
    assert st["diagnostic"] and "NOT FOR PRODUCTION" in f.read_text()
    cuts = simulate_iso(str(f), MachineProfile())
    assert len(cuts) == 28
    src = {(round(p.points[0][0], 2), round(p.points[0][1], 2)): p.points + [p.points[0]]
           for p in sc.paths if p.layer == "CUT"}
    assert len(src) == 28
    for c in cuts:
        s = src[(round(c[0][0], 2), round(c[0][1], 2))]
        assert _maxdev(s, c) <= math.sqrt(2) * 0.005 + 1e-9  # 2 decimals in x and y


def test_project_roundtrip_without_sources(scb, tmp_path):
    f = tmp_path / "p.l7n"
    save_project(scb.project, str(f))
    q = load_project(str(f))
    assert q.sources[0].sha256 == scb.container.sha256
    a, b = scb.project.pieces[6], q.pieces[6]
    assert a.name == b.name and list(a.sizes) == list(b.sizes)
    assert a.sizes["44"].cut == b.sizes["44"].cut
    assert [(pl.x, pl.y, pl.rotation, pl.mirrored) for pl in scb.project.markers[0].placements] == \
           [(pl.x, pl.y, pl.rotation, pl.mirrored) for pl in q.markers[0].placements]
    assert os.path.getsize(f) > 0
