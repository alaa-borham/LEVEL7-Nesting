"""Remnant: small pieces packed together so the fabric left over is one large piece (LEVEL7 MTM owner)."""
from level7.model import FabricSettings, Marker, NestSettings, Piece, PieceGeometry, Placement, Project
from level7.nesting.remnant import consolidate, largest_rect
from level7.validation.checker import validate_marker


def _rect(w, h):
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


def _project():
    long_ = Piece(uid="L", source_id="L", number=1, name="long", sizes={"s": PieceGeometry(size="s", cut=_rect(1800, 300))},
                  allowed_rotations=[0.0, 180.0])
    small = Piece(uid="S", source_id="S", number=2, name="small", sizes={"s": PieceGeometry(size="s", cut=_rect(120, 100))},
                  allowed_rotations=[0.0, 180.0])
    proj = Project(name="t", pieces=[long_, small])
    pls = [Placement(uid="l1", piece_uid="L", size="s", x=0, y=0), Placement(uid="l2", piece_uid="L", size="s", x=0, y=300)]
    for k, (x, y) in enumerate([(100, 700), (900, 820), (1500, 650), (400, 880), (1300, 760), (1650, 880)]):
        pls.append(Placement(uid=f"s{k}", piece_uid="S", size="s", x=x, y=y))
    marker = Marker(name="m", fabric=FabricSettings(width=1000.0), placements=pls, length=1800.0)
    return proj, marker


def test_largest_rect():
    import numpy as np
    free = np.ones((4, 6), dtype=bool)
    free[1, 2] = False
    assert largest_rect(free)[0] == 12                          # the 2 x 6 block below the taken cell


def test_small_pieces_packed_into_one_free_area():
    proj, marker = _project()
    assert validate_marker(proj, marker).ok
    out, info = consolidate(proj, marker, NestSettings(), validate=lambda m: validate_marker(proj, m).ok)
    assert info["done"] and info["after_m2"] > info["before_m2"] * 1.5, info
    assert validate_marker(proj, out).ok
    xs = [pl.x + 120 for pl in out.placements if pl.piece_uid == "S"]
    assert max(xs) <= 1800 + 1e-6                               # never longer
    assert [pl.x for pl in out.placements if pl.piece_uid == "L"] == [0, 0]   # long pieces stay


def test_nothing_changes_without_gain():
    proj, marker = _project()
    marker.placements = marker.placements[:2]
    out, info = consolidate(proj, marker, NestSettings())
    assert out is None
