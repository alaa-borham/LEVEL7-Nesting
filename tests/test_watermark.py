"""Watermark (logo / word) on the pieces: placed inside every piece, readable on turned and mirrored copies,
saved in the project, printed - and never written into the cutting files."""
import base64
import math
import os

import pytest
from conftest import SAMPLES, SCB
from shapely.geometry import Point, Polygon

from level7 import watermark as W
from level7.geometry import placement_points
from level7.service import export_marker, open_any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
LOGO = os.path.join(SAMPLES, "watermark", "level7_logo.webp")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _cfg(**kw):
    c = dict(W.DEFAULTS, enabled=True, kind="image", image_b64=base64.b64encode(open(LOGO, "rb").read()).decode())
    c.update(kw)
    return c


def _check(proj, m, cfg, aspect=2.19):
    n = 0
    for pl in m.placements:
        pc = proj.piece(pl.piece_uid)
        c = W.placement_corners(pc, pl, cfg, aspect)
        if c is None:
            continue
        n += 1
        tl, tr, bl = c
        br = (tr[0] + bl[0] - tl[0], tr[1] + bl[1] - tl[1])
        poly = Polygon(placement_points(pc.sizes[pl.size].cut, pl)).buffer(0.5)
        assert all(poly.contains(Point(q)) for q in (tl, tr, bl, br))          # inside its piece
        u = (tr[0] - tl[0], tr[1] - tl[1])
        v = (tl[0] - bl[0], tl[1] - bl[1])
        assert u[0] * v[1] - u[1] * v[0] > 0                                    # never mirror-written
        if cfg.get("upright", True):
            assert u[0] > -1e-6                                                 # reads left to right
        assert math.hypot(*u) <= cfg["max_mm"] + 1e-6
        assert abs(math.hypot(*u) / math.hypot(*v) - aspect) < 0.05 * aspect
    return n


@pytest.mark.parametrize("pos", W.POSITIONS)
@pytest.mark.parametrize("align", ["grain", "long"])
def test_inside_every_piece_and_readable(pos, align):
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    placed = sum(1 for p in m.placements if p.placed)
    n = _check(proj, m, _cfg(position=pos, align=align))
    assert n >= 0.7 * placed                                  # only very small pieces go without it


def test_turns_with_the_piece_when_not_upright():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    assert any(p.rotation % 360 == 180 for p in m.placements)
    _check(proj, m, _cfg(upright=False))


def test_excluded_pieces_and_switched_off():
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    pc = proj.piece(m.placements[0].piece_uid)
    cfg = _cfg(excluded=[pc.uid])
    assert all(W.placement_corners(pc, pl, cfg, 2.0) is None for pl in m.placements if pl.piece_uid == pc.uid)
    assert not W.active(dict(cfg, enabled=False))
    assert not W.active(dict(cfg, image_b64=""))
    assert W.active(dict(cfg, kind="text", text="LEVEL7")) and not W.active(dict(cfg, kind="text", text="  "))


def test_saved_in_the_project(tmp_path):
    from level7.project_storage.store import load_project, save_project
    proj, _ = open_any(SCB)
    proj.watermark = _cfg(position="top", excluded=[proj.pieces[0].uid])
    save_project(proj, str(tmp_path / "p.l7n"))
    assert load_project(str(tmp_path / "p.l7n")).watermark == proj.watermark


def test_not_in_the_cutting_files(tmp_path):
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    out = {}
    for on in (False, True):
        proj.watermark = _cfg(enabled=on)
        for fmt in ("plt", "dxf", "iso"):
            p = tmp_path / f"{on}.{fmt}"
            export_marker(proj, m, fmt, str(p), diagnostic_iso=fmt == "iso", job_name="job")
            out[(on, fmt)] = p.read_bytes()
    for fmt in ("plt", "iso"):
        assert out[(False, fmt)] == out[(True, fmt)]
    a, b = (out[(k, "dxf")].decode("latin-1").splitlines() for k in (False, True))
    assert len(a) == len(b)                                  # (DXF carries a time stamp / handles only)


@pytest.mark.parametrize("kind,color", [("image", "original"), ("image", "dark"), ("text", "light")])
def test_drawn_on_screen_and_printed(app, tmp_path, kind, color):
    from PySide6.QtPrintSupport import QPrinter

    from level7.ui import printing
    from level7.ui.marker_view import MarkerView, WatermarkItem
    proj, _ = open_any(SCB)
    m = proj.markers[0]
    proj.watermark = _cfg(kind=kind, color=color, text="LEVEL7")
    v = MarkerView()
    v.show_marker(proj, m)
    items = [c for it in v.items_by_uid.values() for c in it.children_items if isinstance(c, WatermarkItem)]
    assert len(items) >= 0.7 * len(v.items_by_uid)
    v.viewport().grab()
    job = printing.build_job(proj, m, m.placements, "t", "i")
    assert job.art is not None and len(job.marks) == len(items)
    assert not printing.build_job(proj, m, m.placements, "t", "i", watermark=False).marks
    pr = QPrinter(QPrinter.HighResolution)
    printing.setup_printer(pr, job)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(str(tmp_path / "w.pdf"))
    assert printing.paint(pr, job) == 1
    proj.watermark["enabled"] = False
    v.refresh_watermark()
    assert not [c for it in v.items_by_uid.values() for c in it.children_items if isinstance(c, WatermarkItem)]


def test_svg_logo(app):
    from level7.ui.watermark_art import Art
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" ' \
          b'fill="red"/></svg>'
    a = Art(dict(W.DEFAULTS, enabled=True, image_b64=base64.b64encode(svg).decode()))
    assert a.ok and abs(a.aspect - 2.0) < 0.01
    assert not Art(dict(W.DEFAULTS, enabled=True, image_b64=base64.b64encode(b"not an image").decode())).ok
