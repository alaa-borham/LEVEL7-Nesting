"""A big job's first layout can take longer than the time given: the time limit and Stop still end the run
at once and return the pieces placed so far (the others reported as not placed)."""
import os
import threading
import time

from conftest import MDL

from level7.model import FabricSettings, NestSettings
from level7.nesting.engine import HALT_REASON, NestEngine, build_items
from level7.service import open_any

VEST = os.path.join(os.path.dirname(MDL), "vest2027", "vest2027-M1.mdl")


def _engine(limit, stop=None):
    proj, _ = open_any(VEST)
    sizes = {s: 2 for s in proj.size_names}
    fab, st = FabricSettings(width=1500.0), NestSettings(time_limit=limit, seed=1)
    items, _, _ = build_items(proj, sizes, proj.cut_order.piece_counts, fab, st)
    return NestEngine(items, fab, st, stop_event=stop), items


def test_time_limit_ends_the_first_layout_with_a_partial_result():
    eng, items = _engine(2.0)
    t = time.monotonic()
    res = eng.run()
    assert time.monotonic() - t < 2.0 + 3.0
    assert res.placements and res.unplaced
    assert len(res.placements) + len(res.unplaced) == len(items)
    assert any(u.reason == HALT_REASON for u in res.unplaced)


def test_stop_answers_at_once():
    ev = threading.Event()
    eng, _ = _engine(600.0, ev)
    threading.Timer(2.0, ev.set).start()
    t = time.monotonic()
    res = eng.run()
    assert time.monotonic() - t < 2.0 + 2.0
    assert res.placements and res.stopped
