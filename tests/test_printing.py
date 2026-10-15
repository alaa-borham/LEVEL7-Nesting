"""Printing (A4 / A3): page counts and PDF output for the whole marker, selected pieces and real size (1:1)."""
import os

import pytest
from conftest import SCB

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pdf(job, path):
    from PySide6.QtPrintSupport import QPrinter

    from level7.ui import printing
    pr = QPrinter(QPrinter.HighResolution)
    printing.setup_printer(pr, job)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(str(path))
    return printing.page_count(pr, job), printing.paint(pr, job)


def test_print_whole_selected_and_real_size(app, tmp_path):
    from level7.service import open_any
    from level7.ui import printing
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    job = printing.build_job(proj, m, m.placements, "t", "info", paper="A4")
    assert job.fabric is not None and len(job.pieces) == sum(1 for p in m.placements if p.placed)
    assert _pdf(job, tmp_path / "a.pdf") == (1, 1)
    sel = printing.build_job(proj, m, m.placements[:2], "t", "info", paper="A4")
    assert sel.fabric is None and len(sel.pieces) == 2
    assert _pdf(sel, tmp_path / "s.pdf") == (1, 1)
    real = printing.build_job(proj, m, m.placements, "t", "info", paper="A3", real_size=True)
    n, painted = _pdf(real, tmp_path / "r.pdf")
    # 1:1 pages cover the whole marker: (columns - 1) steps + one page >= its length / width
    assert n == painted and n > 1
    for f in ("a.pdf", "s.pdf", "r.pdf"):
        assert (tmp_path / f).stat().st_size > 1000
