"""GRAFIS AAMA export (samples/reference/aama: DXF base size + RUL grading) vs LEVEL7's native MDL reading.

* every graded cut-line point (base + RUL delta) of every size must lie on LEVEL7's MDL contour of that
  size (independent check of the cut contours in all 14 sizes);
* the AAMA reader itself (additional import path) reproduces the base exactly and the notches.
"""
import math
import os

import ezdxf
import pytest
from conftest import MDL, SAMPLES
from shapely.geometry import LinearRing, Point, Polygon

from level7.readers.aama import _delta, read_aama, read_rul, size_columns
from level7.readers.grafis import read_grafis

DXF = os.path.join(SAMPLES, "reference", "aama", "Neay_blue_pants.dxf")
RUL = os.path.join(SAMPLES, "reference", "aama", "Neay_blue_pants.rul")


@pytest.fixture(scope="module")
def mdl():
    return read_grafis(MDL).project


def test_graded_points_lie_on_mdl_contours_all_sizes(mdl):
    sizes, sample, rules = read_rul(RUL)
    cols, dup = size_columns(sizes, sample)
    doc = ezdxf.readfile(DXF, encoding="cp1256")
    checked, worst = 0, 0.0
    for b in [b for b in doc.blocks if not b.name.startswith("*")]:
        num = int(b.name.split("_")[1])
        piece = next(p for p in mdl.pieces if p.number == num)
        ents = list(b)
        poly = [e for e in ents if e.dxftype() == "POLYLINE" and e.dxf.layer == "1"][0]
        base = [(v.dxf.location.x, v.dxf.location.y) for v in poly.vertices]
        assert Polygon(base).exterior.hausdorff_distance(Polygon(piece.sizes["base:__HN40_0"].cut).exterior) < 0.001
        for e in ents:
            if e.dxftype() == "TEXT" and e.dxf.layer == "1" and e.dxf.text.startswith("#"):
                v = min(base, key=lambda t: math.dist(t, (e.dxf.insert.x, e.dxf.insert.y)))
                rule = rules[int(e.dxf.text[1:])]
                for size in mdl.size_names:
                    dx, dy = _delta(rule, cols, dup, size, sample)
                    d = LinearRing(piece.sizes[size].cut).distance(Point(v[0] + dx, v[1] + dy))
                    worst = max(worst, d)
                    checked += 1
    assert checked == 165 * 14                                 # 165 grade points x 14 sizes
    assert worst <= 0.0071                                     # RUL deltas have 2 decimals


def test_aama_reader(mdl):
    proj, issues = read_aama(DXF)
    assert not issues and len(proj.pieces) == 11 and len(proj.size_names) == 14
    names = {p.name for p in proj.pieces}
    assert "ورقه جيب الصدر" in names                     # Arabic decoded (Windows-1256)
    front = next(p for p in proj.pieces if p.number == 7)
    mfront = next(p for p in mdl.pieces if p.number == 7)
    assert front.material == "O" and front.grain_angle == pytest.approx(90.0)
    # base (sample) exact; graded sizes approximate (non-graded curve points interpolated)
    assert Polygon(front.sizes["28"].cut).exterior.hausdorff_distance(Polygon(mfront.sizes["28"].cut).exterior) < 0.01
    # notches: same bases as the MDL cut notches, in size 44
    ours = [n.position for n in mfront.sizes["44"].notches]
    theirs = [n.position for n in front.sizes["44"].notches]
    assert len(theirs) == len(ours) == 5
    assert all(min(math.dist(a, b) for b in ours) < 0.01 for a in theirs)
