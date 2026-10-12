"""All 15 grading entries vs GRAFIS piece DXF exports (samples/reference/pieces/Neay_blue_pants_0NN.dxf;
one layer per GRDTAB entry: layer k = entry k+1). These exports contain grain lines and size texts."""
import glob
import math
import os

import ezdxf
import pytest
from conftest import MDL, SAMPLES

from level7.readers.grafis import read_grafis

FILES = sorted(glob.glob(os.path.join(SAMPLES, "reference", "pieces", "*.dxf")))


@pytest.fixture(scope="module")
def mdl_project():
    return read_grafis(MDL)


@pytest.mark.parametrize("path", FILES, ids=[os.path.basename(f) for f in FILES])
def test_grain_and_texts_all_sizes(mdl_project, path):
    r = mdl_project
    num = int(os.path.basename(path).split("_")[-1][:3])
    piece = next(p for p in r.project.pieces if p.number == num)
    names = {s.index: s.name for s in r.text.sizes}
    msp = ezdxf.readfile(path).modelspace()
    layers = sorted({e.dxf.layer for e in msp}, key=int)
    assert len(layers) == 15
    for layer in layers:
        idx = int(layer) + 1
        key = names[idx] if idx != 1 else f"base:{names[idx]}"
        g = piece.sizes[key]
        # grain arrow (6-point polyline) identical
        ref = [[(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
               for e in msp.query(f'POLYLINE[layer=="{layer}"]')]
        assert g.grain is not None and len(ref) == 1
        assert max(math.dist(a, b) for a, b in zip(ref[0], g.grain.points)) < 1e-3
        # size texts: same string, height, angle and insertion point
        for t in msp.query(f'TEXT[layer=="{layer}"]'):
            lb = min(g.labels, key=lambda l: math.dist(l.position, (t.dxf.insert.x, t.dxf.insert.y)))
            assert lb.text == t.dxf.text
            assert lb.height == pytest.approx(t.dxf.height, abs=1e-4)
            assert lb.angle == pytest.approx(t.dxf.rotation, abs=1e-3)
            assert math.dist(lb.position, (t.dxf.insert.x, t.dxf.insert.y)) < 0.01
