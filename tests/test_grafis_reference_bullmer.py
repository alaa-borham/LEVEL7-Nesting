"""LEVEL7 Bullmer ISO (GRAFIS 'Bullmer-Cutter (typical)' compatible) vs GRAFIS' own cut file of the
1500 mm marker (samples/reference/Neay blue pants-44-1500.iso). Geometry comes from the SCB only."""
import math
import os
import re

import pytest
from conftest import SAMPLES
from shapely.geometry import LineString

from level7.exporters.iso import bullmer_grafis_profile, write_iso
from level7.exporters.scene import marker_scene
from level7.readers.grafis import read_grafis

REF = os.path.join(SAMPLES, "reference", "Neay blue pants-44-1500.iso")
SCB1500 = os.path.join(SAMPLES, "Neay blue pants-44-1500.scb")
TOL = 0.15   # both files rounded to 0.1 mm


def parse(path):
    d = open(path, "rb").read().decode("latin-1")
    blocks = [b.strip() for b in d.replace("\r\n", "").split("*") if b.strip()]
    pieces, cur, down, pos, stroke = [], None, False, None, None
    for b in blocks:
        m = re.fullmatch(r"X(-?\d+)Y(-?\d+)", b)
        if m:
            pos = (int(m[1]) / 10, int(m[2]) / 10)
            if down:
                stroke.append(pos)
            continue
        if re.fullmatch(r"N\d+", b):
            cur = {"strokes": []}
            pieces.append(cur)
        elif b == "M14":
            down, stroke = True, [pos]
        elif b == "M15":
            if down and stroke and len(stroke) > 1:
                cur["strokes"].append(stroke)
            down = False
    return pieces, blocks, d


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    r = read_grafis(SCB1500)
    out = tmp_path_factory.mktemp("iso") / "l7.iso"
    st = write_iso(marker_scene(r.project, r.project.markers[0]), str(out), bullmer_grafis_profile(),
                   job_name="Neay blue pants-44-1500")
    return parse(REF), parse(str(out)), st


def test_header_footer_and_block_set(files):
    (rp, rb, rd), (op, ob, od), st = files
    assert rd.splitlines()[:2] == od.splitlines()[:2]       # H1*G71*M70*D2*M15* / M20*NAME/L=2.85m/B=1.50m*
    assert rd.rstrip().endswith("M15*D4*M00*") and od.rstrip().endswith("M15*D4*M00*")
    kinds = lambda bl: {re.sub(r"-?\d+", "#", b) for b in bl}
    assert kinds(ob) == kinds(rb)
    assert len(rp) == len(op) == st["pieces"] == 28


def test_each_piece_identical_cut_sequence(files):
    (rp, _, _), (op, _, _), _ = files
    used = set()
    for pc in rp:
        allr = [q for s in pc["strokes"] for q in s]
        c = LineString(allr).centroid
        j = min((k for k in range(len(op)) if k not in used),
                key=lambda k: LineString([q for s in op[k]["strokes"] for q in s]).centroid.distance(c))
        used.add(j)
        ours = op[j]["strokes"]
        assert len(ours) == len(pc["strokes"])                       # same number of notch plunges
        for a, b in zip(pc["strokes"], ours):                       # same start, direction and points
            assert len(a) == len(b)
            assert max(math.dist(p, q) for p, q in zip(a, b)) <= TOL
