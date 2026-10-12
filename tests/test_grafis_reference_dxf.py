"""Independent check against GRAFIS' own DXF export of the 1500 mm marker (samples/reference/44-150.dxf).

GRAFIS layers: 1 = cut contour with notch slits as 5 mm spikes, 8 = seam line (with seam notch
spikes) and size texts. Our geometry comes only from the SCB file; nothing is read from the DXF.
"""
import math
import os

import ezdxf
import pytest
from conftest import SAMPLES
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from level7.exporters.scene import marker_scene
from level7.readers.grafis import read_grafis

REF = os.path.join(SAMPLES, "reference", "44-150.dxf")
SCB1500 = os.path.join(SAMPLES, "Neay blue pants-44-1500.scb")
TOL = 0.01  # mm


def _strip_spikes(pts):
    out, spikes = list(pts), []
    changed = True
    while changed:
        changed = False
        for i in range(1, len(out) - 1):
            if math.dist(out[i - 1], out[i + 1]) < 1e-3:
                spikes.append((out[i - 1], out[i]))
                del out[i:i + 2]
                changed = True
                break
    return out, spikes


@pytest.fixture(scope="module")
def data():
    doc = ezdxf.readfile(REF)
    cut, seam, texts = [], [], []
    for b in doc.blocks:
        if b.name.startswith("*"):
            continue
        for e in b:
            if e.dxftype() == "POLYLINE":
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            elif e.dxftype() == "LINE":
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif e.dxftype() == "TEXT":
                texts.append((e.dxf.text, (e.dxf.insert.x, e.dxf.insert.y), e.dxf.height))
                continue
            else:
                continue
            (cut if e.dxf.layer == "1" else seam).append(pts)
    r = read_grafis(SCB1500)
    sc = marker_scene(r.project, r.project.markers[0])
    return cut, seam, texts, sc


def test_cut_contours_match_grafis(data):
    cut, _, _, sc = data
    ours = [Polygon(p.points) for p in sc.paths if p.layer == "CUT"]
    assert len(cut) == len(ours) == 28
    used = set()
    for pts in cut:
        clean, _ = _strip_spikes(pts)
        P = Polygon(clean)
        j = min((k for k in range(28) if k not in used), key=lambda k: ours[k].centroid.distance(P.centroid))
        used.add(j)
        assert P.exterior.hausdorff_distance(ours[j].exterior) < TOL


def test_cut_notches_match_grafis(data):
    cut, _, _, sc = data
    ref = [s for pts in cut for s in _strip_spikes(pts)[1]]
    ours = [p.points for p in sc.paths if p.layer == "NOTCH"]
    assert len(ours) == 44
    matched = sum(1 for a, b in ref if any(math.dist(a, u) < TOL and math.dist(b, v) < TOL for u, v in ours))
    assert matched == 44 and len(ref) == 46   # 2 extra 6.7 mm slits exist only on two GRAFIS front copies
    for a, b in ref:   # every GRAFIS slit starts at one of our notch bases
        assert any(math.dist(a, u) < TOL for u, _ in ours)


def test_seam_lines_match_grafis(data):
    _, seam, _, sc = data
    ref = unary_union([LineString(p) for p in seam])
    ours = unary_union([LineString(p.points + ([p.points[0]] if p.closed else [])) for p in sc.paths
                        if p.layer == "SEAM"])
    assert ours.difference(ref.buffer(TOL)).length < 1.0          # ours within GRAFIS
    assert ref.difference(ours.buffer(TOL)).length < 1.0          # GRAFIS within ours (incl. seam notches)
    spikes = [s for p in seam for s in _strip_spikes(p)[1]]
    assert len(spikes) == 24
    for a, b in spikes:
        assert ours.distance(Point(a)) < TOL and ours.distance(Point(b)) < TOL


def test_size_texts_match_grafis(data):
    _, _, texts, sc = data
    ours = [t for t in sc.texts if t.layer == "TEXT"]
    assert len(ours) == len(texts) == 16
    for txt, pos, h in texts:
        best = min(ours, key=lambda t: math.dist(t.position, pos))
        assert best.text == txt and best.height == pytest.approx(h, abs=1e-4)
        assert math.dist(best.position, pos) < 0.01
