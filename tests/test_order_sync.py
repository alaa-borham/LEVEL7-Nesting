"""The marker follows the cut order at once (sizes / quantities / parts changed after nesting)."""
from conftest import SCB

from level7.service import ADDED_TO_ORDER, open_any, sync_marker_to_order


def test_marker_follows_size_quantities():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    assert sync_marker_to_order(proj, m) == (0, 0)          # a GRAFIS marker matches its own order
    per_bundle = len(m.placements) // 2
    proj.cut_order.size_quantities["44"] = 1
    assert sync_marker_to_order(proj, m) == (per_bundle, 0)
    assert {pl.bundle for pl in m.placements} == {1} and all(pl.placed for pl in m.placements)
    proj.cut_order.size_quantities["44"] = 3
    assert sync_marker_to_order(proj, m) == (0, 2 * per_bundle)
    new = [pl for pl in m.placements if not pl.placed]
    assert len(new) == 2 * per_bundle and {pl.bundle for pl in new} == {2, 3}
    assert all(pl.reason == ADDED_TO_ORDER for pl in new) and len({pl.uid for pl in m.placements}) == len(m.placements)
    proj.cut_order.size_quantities["44"] = 2                 # unplaced copies leave first
    sync_marker_to_order(proj, m)
    assert sum(pl.placed for pl in m.placements) == per_bundle and len(m.placements) == 2 * per_bundle


def test_part_switched_off_leaves_the_marker():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    uid = m.placements[0].piece_uid
    n = sum(1 for pl in m.placements if pl.piece_uid == uid)
    proj.cut_order.piece_counts[uid] = (0, 0)
    assert sync_marker_to_order(proj, m) == (n, 0)
    assert all(pl.piece_uid != uid for pl in m.placements)


def test_excluded_rows_and_pinned_copies_are_kept():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    proj.cut_order.excluded = [["44", 2]]                    # switched off for the next run only
    assert sync_marker_to_order(proj, m) == (0, 0)
    uid = m.placements[0].piece_uid
    n, mm = proj.cut_order.piece_counts[uid]
    proj.cut_order.excluded = []
    pinned = next(pl for pl in m.placements if pl.piece_uid == uid and pl.bundle == 1 and not pl.mirrored)
    pinned.pinned = True
    proj.cut_order.piece_counts[uid] = (n + 1, mm)           # one more copy: added unplaced, then placed by hand
    sync_marker_to_order(proj, m)
    extra = next(pl for pl in m.placements if pl.piece_uid == uid and pl.bundle == 1 and not pl.placed)
    extra.placed = True
    proj.cut_order.piece_counts[uid] = (n, mm)
    sync_marker_to_order(proj, m)
    assert pinned in m.placements and extra not in m.placements   # the pinned copy stays, the other leaves


def test_copies_ordered_again_come_back_in_place():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    before = {(pl.piece_uid, pl.bundle, pl.mirrored, round(pl.x, 3), round(pl.y, 3)) for pl in m.placements}
    spare = []
    proj.cut_order.size_quantities["44"] = 0
    sync_marker_to_order(proj, m, spare)
    assert not m.placements
    proj.cut_order.size_quantities["44"] = 2
    sync_marker_to_order(proj, m, spare)
    assert {(pl.piece_uid, pl.bundle, pl.mirrored, round(pl.x, 3), round(pl.y, 3)) for pl in m.placements} == before
    assert all(pl.placed for pl in m.placements)
