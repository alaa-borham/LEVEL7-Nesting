"""Batch marker orders: list parsing (CSV / Excel, Arabic headers), per-marker build, nesting, save, export."""
import os

import pytest
from conftest import MDL, SCB

from level7 import batch

HERE = os.path.dirname(os.path.abspath(__file__))
VEST = os.path.join(HERE, "..", "samples", "vest2027", "OUT vest2027-M1-M.scb")


def write_csv(tmp_path, rows):
    f = tmp_path / "orders.csv"
    f.write_text("\n".join(",".join(r) for r in rows), encoding="utf-8")
    return str(f)


def test_parse_arabic_headers_and_continuation_rows(tmp_path):
    f = write_csv(tmp_path, [["ماركر", "ملف", "مقاس", "كمية", "عرض", "خامة", "صيغ", "وقت"],
                             ["A1", SCB, "44", "2", "1500", "O", "plt;iso", "5"],
                             ["", "", "46", "1", "", "", "", ""],
                             ["A2", MDL, "40", "1", "1430", "", "dxf", ""]])
    o = batch.parse_orders(f)
    assert [x.name for x in o] == ["A1", "A2"]
    assert [(l.size, l.qty) for l in o[0].lines] == [("44", 2), ("46", 1)] and o[0].formats == ["plt", "iso"]
    assert o[1].width == 1430.0 and o[1].formats == ["dxf"]


def test_errors_are_clear(tmp_path):
    with pytest.raises(batch.OrderError, match="missing columns"):
        batch.parse_orders(write_csv(tmp_path, [["marker", "size"], ["x", "1"]]))
    with pytest.raises(batch.OrderError, match="unknown format"):
        batch.parse_orders(write_csv(tmp_path, [["marker", "file", "size", "qty", "width", "formats"],
                                                ["x", SCB, "44", "1", "1500", "pdf"]]))
    with pytest.raises(batch.OrderError, match="width"):
        batch.parse_orders(write_csv(tmp_path, [["marker", "file", "size", "qty"], ["x", SCB, "44", "1"]]))


def test_run_batch_two_models_exports_and_failure_isolated(tmp_path):
    from level7.exporters.iso import ISO_PRESETS
    from level7.exporters.plt import PRESETS
    f = write_csv(tmp_path, [["marker", "file", "size", "qty", "width", "material", "formats", "time"],
                             ["M1", SCB, "44", "1", "1500", "O", "plt;iso", "4"],
                             ["M1", VEST, "m", "1", "", "", "", ""],
                             ["M2", MDL, "XXL", "1", "1500", "", "dxf", "3"]])
    orders = batch.parse_orders(f)
    out = tmp_path / "out"
    summary = batch.run_batch(orders, str(out), PRESETS["algotex_grafis"](), ISO_PRESETS["bullmer_grafis"]())
    m1, m2 = orders
    assert m1.status == "done" and m1.length_mm and {os.path.basename(x) for x in m1.outputs} == \
        {"M1.l7n", "M1.plt", "M1.iso"}
    assert m2.status == "failed" and "XXL" in m2.message                # reported, batch continued
    assert os.path.isfile(summary)
    from level7.project_storage.store import load_project
    p = load_project(str(out / "M1.l7n"))
    assert len(p.markers[-1].placements) == 27 and all(pl.placed for pl in p.markers[-1].placements)


def test_excel_template_roundtrip(tmp_path):
    f = str(tmp_path / "t.xlsx")
    batch.write_template(f)
    o = batch.parse_orders(f)
    assert [x.name for x in o] == ["M001", "M002"] and len(o[0].lines) == 3
