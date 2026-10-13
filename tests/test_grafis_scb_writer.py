"""GRAFIS SCB writer: template based; GRAFIS' own markers are rewritten byte for byte, LEVEL7 markers are
re-read identically (positions, validation, SBINFO / SBGRLST)."""
import math
import os
import struct

import pytest
from conftest import SCB

from level7 import service
from level7.formats.grafis.container import read_container
from level7.formats.grafis.placements import decode_marker
from level7.formats.grafis.writer import ScbWriteError, pivot, write_scb
from level7.geometry import placement_points
from level7.model import FabricSettings, NestSettings
from level7.readers.grafis import read_grafis
from level7.validation.checker import validate_marker

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "..", "samples")
ALL_SCB = [SCB, os.path.join(SAMPLES, "Neay blue pants-44-1500.scb"),
           os.path.join(SAMPLES, "vest2027", "OUT vest2027-M1-M.scb")]


@pytest.mark.parametrize("path", ALL_SCB)
def test_rewrite_of_grafis_marker_is_byte_identical(path, tmp_path):
    r = read_grafis(path)
    out = tmp_path / "x.scb"
    write_scb(path, r.project, r.project.markers[0], str(out))
    assert out.read_bytes() == open(path, "rb").read()


@pytest.mark.parametrize("path", ALL_SCB)
def test_pivot_formula_matches_every_grafis_record(path):
    _, recs, _ = decode_marker(read_container(path).by_id()[(2, 8, 0, 0)].payload)
    for r in recs:
        if abs(r.base_rot + 90) < 1e-6:
            px, py = pivot(r.xmin, r.ymin, r.bbox_w, r.bbox_h)
            gx, gy = struct.unpack_from("<2f", r.raw, 64)
            assert abs(px - gx) < 1e-3 and abs(py - gy) < 1e-3


@pytest.mark.parametrize("path,width,sizes", [(SCB, 1500.0, {"44": 2}), (ALL_SCB[2], 1440.0, {"M": 1, "L": 1})])
def test_level7_marker_written_and_reread_identically(path, width, sizes, tmp_path):
    p, _ = service.open_any(path)
    p.cut_order.size_quantities = {s: sizes.get(s, 0) for s in p.size_names}
    m, info = service.run_nesting(p, FabricSettings(width=width), NestSettings(time_limit=4, seed=1), workers=1)
    out = tmp_path / "new.scb"
    service.export_marker(p, m, "scb", str(out))
    r = read_grafis(str(out))
    q, mm = r.project, r.project.markers[0]
    assert not r.issues and r.checks["bbox_mismatch"] == [] and r.checks["area_mismatch"] == []
    assert validate_marker(q, mm).ok and len(mm.placements) == sum(1 for x in m.placements if x.placed)
    src = {}
    for pl in m.placements:
        pc = p.piece(pl.piece_uid)
        src.setdefault((pc.number, pl.size, pl.mirrored), []).append(placement_points(pc.sizes[pl.size].cut, pl))
    for pl in mm.placements:
        pc = q.piece(pl.piece_uid)
        pts = placement_points(pc.sizes[pl.size].cut, pl)
        best = min(max(math.dist(a, b) for a, b in zip(pts, c)) for c in src[(pc.number, pl.size, pl.mirrored)])
        assert best < 0.01
    assert int(q.sbinfo["PCSTOTAL"]) == len(mm.placements) and q.sbinfo["WIDTH"] == f"{width:.0f}"
    assert sorted(s for _, s in r.text.sbgrlst) == sorted(s for s, n in sizes.items() for _ in range(n))


def test_multi_model_session_refused(tmp_path):
    p, _ = service.open_any(SCB)
    service.add_model(p, ALL_SCB[2])
    with pytest.raises(ScbWriteError):
        write_scb(SCB, p, p.markers[0], str(tmp_path / "x.scb"))
