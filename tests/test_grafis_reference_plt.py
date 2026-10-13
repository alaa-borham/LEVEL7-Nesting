"""LEVEL7 PLT export (Algotex/GRAFIS profile) vs GRAFIS' own PLT of the same 1500 mm marker
(samples/reference/Neay blue pants-44-1500.plt). Geometry is taken from the SCB only."""
import math
import os

import pytest
from conftest import SAMPLES
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from level7.exporters.plt import algotex_grafis_config, read_plt, write_plt
from level7.exporters.scene import marker_scene
from level7.readers.dxf import strip_spikes
from level7.readers.grafis import read_grafis

REF = os.path.join(SAMPLES, "reference", "Neay blue pants-44-1500.plt")
SCB1500 = os.path.join(SAMPLES, "Neay blue pants-44-1500.scb")
GRID = 2 * math.sqrt(2) * 0.5 / 40   # both files independently rounded to the 0.025 mm grid


def _cuts(paths):
    """Cut contours = closed paths not lying inside another closed path (seam rings are inside)."""
    closed = [p.points for p in paths if p.points[0] == p.points[-1]]
    polys = [Polygon(strip_spikes(c[:-1])[0]).buffer(0) for c in closed]
    return [c for i, c in enumerate(closed)
            if not any(j != i and polys[j].area > polys[i].area and polys[j].buffer(0.05).contains(polys[i])
                       for j in range(len(closed)))]


def _is_glyph(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys)) < 16 and pts[0] != pts[-1]


def _non_cut(paths):
    cuts = {id(c) for c in _cuts(paths)}
    return [p.points for p in paths if id(p.points) not in cuts]


@pytest.fixture(scope="module")
def both(tmp_path_factory):
    r = read_grafis(SCB1500)
    sc = marker_scene(r.project, r.project.markers[0])
    out = tmp_path_factory.mktemp("plt") / "l7.plt"
    cfg = algotex_grafis_config()
    cfg.line_type = "lt1"                 # GRAFIS' own header; LEVEL7's default is a solid line (LT)
    st = write_plt(sc, str(out), cfg)
    ref, _ = read_plt(REF)
    ours, labels = read_plt(str(out))
    return ref, ours, labels, st, out


def test_file_framing_like_grafis(both):
    _, _, labels, st, out = both
    raw = open(out, "rb").read()
    ref = open(REF, "rb").read()
    assert raw.startswith(b"IN\r\nLT1\r\nPA") and ref.startswith(b"IN\r\nLT1\r\nPA")
    assert raw.endswith(b"PU\r\nPG\r\n") and ref.endswith(b"PU\r\nPG\r\n")
    assert b";" not in raw and b"SP" not in raw and not labels and st["skipped_chars"] == []


def test_default_line_type_is_solid(tmp_path):
    r = read_grafis(SCB1500)
    sc = marker_scene(r.project, r.project.markers[0])
    out = tmp_path / "solid.plt"
    write_plt(sc, str(out), algotex_grafis_config())
    raw = open(out, "rb").read()
    assert raw.startswith(b"IN\r\nLT\r\nPA")          # LT without a pattern number = continuous line


def test_cut_contours_with_notch_slits(both):
    ref, ours, _, st, _ = both
    rc, oc = _cuts(ref), _cuts(ours)
    assert len(rc) == len(oc) == 28 and st["notches_merged"] == 44
    used = set()
    spikes_ref = spikes_ours = 0
    for pts in rc:
        P = Polygon(strip_spikes(pts[:-1])[0])
        j = min((k for k in range(28) if k not in used),
                key=lambda k: Polygon(strip_spikes(oc[k][:-1])[0]).centroid.distance(P.centroid))
        used.add(j)
        Q, sq = strip_spikes(oc[j][:-1])
        _, sr = strip_spikes(pts[:-1])
        assert P.exterior.hausdorff_distance(Polygon(Q).exterior) <= GRID + 1e-6
        # every one of our notch slits is present in GRAFIS' contour
        for base, tip in sq:
            assert any(math.dist(base, a) <= GRID and math.dist(tip, b) <= GRID for a, b in sr)
        spikes_ref += len(sr)
        spikes_ours += len(sq)
    assert spikes_ours == 44 and spikes_ref == 46     # 2 extra 6.7 mm slits on two GRAFIS front copies


def test_seam_lines(both):
    ref, ours, _, _, _ = both
    def seam(paths):
        return unary_union([LineString(p) for p in _non_cut(paths) if not _is_glyph(p)])
    seam_ref, seam_ours = seam(ref), seam(ours)
    assert seam_ours.difference(seam_ref.buffer(0.03)).length < 1.0
    assert seam_ref.difference(seam_ours.buffer(0.03)).length < 1.0


def test_texts_drawn_as_strokes_near_grafis_texts(both):
    ref, ours, _, st, _ = both
    assert st["text_strokes"] > 0

    def glyph_centres(paths):
        return [LineString(p).centroid for p in _non_cut(paths) if _is_glyph(p)]
    rc, oc = glyph_centres(ref), glyph_centres(ours)
    assert len(rc) == 64
    # every GRAFIS text stroke has one of our text strokes nearby (same text, approximate glyph shapes)
    assert all(min(c.distance(o) for o in oc) < 12 for c in rc)
