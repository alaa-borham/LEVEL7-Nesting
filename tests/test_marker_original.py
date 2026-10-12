from collections import Counter

import pytest

from level7.validation.checker import marker_stats, validate_marker


def test_original_marker_reconstruction(scb):
    p = scb.project
    m = p.markers[0]
    assert m.fabric.width == 1430
    assert len(m.placements) == 28
    v = validate_marker(p, m)
    assert v.ok, [i.message for i in v.issues]   # no overlap, inside width, grain parallel to length
    st = marker_stats(p, m)
    assert st["efficiency_total_width_pct"] == pytest.approx(83.86, abs=0.005)
    assert st["pieces_area_m2"] == pytest.approx(3.51, abs=0.005)
    assert st["length_mm"] == pytest.approx(2929.93, abs=0.01)
    assert scb.checks["bbox_mismatch"] == [] and scb.checks["area_mismatch"] == []
    assert st["garments"] == 2 and round(st["length_per_garment_m"], 2) == 1.46   # GRAFIS "U/B = 1.46 m"


def test_piece_types_and_copies_independent(scb):
    """9 piece types, 28 copies: derived from placements and from #SBTLIST independently."""
    p = scb.project
    m = p.markers[0]
    by_piece = Counter(pl.piece_uid for pl in m.placements)
    assert len(by_piece) == 9
    assert sum(by_piece.values()) == 28
    num = {pc.uid: pc.number for pc in p.pieces}
    sbt = {e.number: (e.count, e.mirrored) for e in scb.text.sbtlist}
    bundles = len(scb.text.sbgrlst)
    for uid, n in by_piece.items():
        c, mi = sbt[num[uid]]
        assert n == bundles * (c + mi)
        mirrored = sum(1 for pl in m.placements if pl.piece_uid == uid and pl.mirrored)
        assert mirrored == bundles * mi
    assert Counter(pl.bundle for pl in m.placements) == {1: 14, 2: 14}


def test_second_marker_1500_variant_vd():
    """Second GRAFIS marker (1500 mm, signature variant 'VD'): same decoding rules, GRAFIS values reproduced."""
    import os

    from conftest import SAMPLES

    from level7.readers.grafis import read_grafis
    r = read_grafis(os.path.join(SAMPLES, "Neay blue pants-44-1500.scb"))
    assert r.container.ok and r.container.variant == "VD" and not r.issues
    p, m = r.project, r.project.markers[0]
    assert m.fabric.width == 1500 and len(m.placements) == 28
    v = validate_marker(p, m)
    assert v.ok, [i.message for i in v.issues]
    st = marker_stats(p, m)
    assert st["efficiency_total_width_pct"] == pytest.approx(82.19, abs=0.01)
    assert st["pieces_area_m2"] == pytest.approx(3.51, abs=0.005)
    assert st["length_mm"] == pytest.approx(r.checks["header_length"], abs=0.1)   # GRAFIS 2849.93
    assert round(st["length_per_garment_m"], 2) == 1.42                            # GRAFIS "U/B = 1.42 m"
    # rotation/mirror combinations not present in the first marker are exercised here
    assert any(pl.mirrored and pl.rotation % 360 == 90 for pl in m.placements)
