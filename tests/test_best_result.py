"""Best result: several attempts with different seeds, the shortest valid marker is kept."""
from conftest import SCB

from level7.model import FabricSettings, NestSettings
from level7.service import open_any, run_nesting


def test_best_of_keeps_the_shortest_valid_attempt():
    proj, _ = open_any(SCB)
    seen = []
    m, info = run_nesting(proj, FabricSettings(width=1430.0),
                          NestSettings(time_limit=2, seed=1, engine="builtin", best_of=3), workers=1,
                          progress=lambda d: seen.append((d.get("attempt"), d.get("attempts"))))
    assert info["validation"].ok
    tried = info["attempts"]
    assert len(tried) == 3 and len({s for s, _l, _ok in tried}) == 3
    assert abs(m.length - min(L for _s, L, ok in tried if ok)) < 0.1
    assert {a for a, n in seen if n == 3} == {1, 2, 3}


def test_batch_attempts_column(tmp_path):
    from level7 import batch
    lst = tmp_path / "o.csv"
    lst.write_text(f"marker,file,size,qty,width,time,محاولات\nM1,{SCB},44,1,1500,2,2\n", encoding="utf-8")
    orders = batch.parse_orders(str(lst))
    assert orders[0].attempts == 2
