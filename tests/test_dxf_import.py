import copy
import os

from conftest import SAMPLES

from level7.model import FabricSettings, NestSettings
from level7.readers.dxf import read_dxf
from level7.service import run_nesting

REF = os.path.join(SAMPLES, "reference", "44-150.dxf")


def test_import_grafis_dxf_export():
    proj, issues = read_dxf(REF)
    assert len(proj.pieces) == 28
    assert sum(len(p.sizes["base"].notches) for p in proj.pieces) == 46
    assert sum(1 for p in proj.pieces if p.sizes["base"].seam) == 12     # 4 fronts, 4 backs, 4 chest pockets
    # no grain layer in this export -> grain is unknown and nesting must refuse those pieces
    assert any("grain" in i for i in issues)
    marker, info = run_nesting(copy.deepcopy(proj), FabricSettings(width=1500), NestSettings(time_limit=2),
                               workers=1)
    assert all(not pl.placed and "grain" in pl.reason for pl in marker.placements)


def test_import_grafis_dxf_then_define_grain_and_nest():
    proj, _ = read_dxf(REF)
    for p in proj.pieces:     # pieces are placed in the marker with grain along X
        p.grain_angle = 0.0
    marker, info = run_nesting(proj, FabricSettings(width=1500), NestSettings(time_limit=4, seed=1), workers=1)
    assert info["validation"].ok and sum(pl.placed for pl in marker.placements) == 28
