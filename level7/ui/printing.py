"""Printing on A4 / A3: the whole marker or the selected pieces, fitted on one page or at real size (1:1) on several
pages to tape together. Drawn from the cut contours on white (not a screenshot of the view): outline, light fill,
piece name and size; a header with marker name, length, width, efficiency, pieces, scale and date on every page."""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtPrintSupport import QPrinter

from ..geometry import bbox, placement_points

HEADER_MM = 12.0          # header band on every page
OVERLAP_MM = 8.0          # 1:1 pages overlap this much (glue strip with registration marks)
MARGIN_MM = 8.0           # around the drawing on the paper (inside the printer's own margins)
PAPERS = {"A4": QPageSize.A4, "A3": QPageSize.A3}


@dataclass
class PrintJob:
    pieces: list                       # [(points mm, label)] in marker coordinates (x = length, y = width)
    world: tuple                       # (x0, y0, x1, y1) mm drawn area
    fabric: tuple | None               # (length, width) - the fabric outline (whole marker only)
    title: str
    info: str                          # "L 4.24 m   W 1.48 m   E 81.4 %   42 pieces"
    paper: str = "A4"
    orientation: str = "auto"          # auto / portrait / landscape
    real_size: bool = False            # True: 1:1 on several pages
    names: bool = True
    fill: bool = True
    extra: dict = field(default_factory=dict)
    marks: list = field(default_factory=list)  # watermark corners (tl, tr, bl) in marker mm, one per piece
    art: object = None                         # watermark_art.Art drawing them


def build_job(project, marker, placements, title, info, watermark: bool = True, **kw) -> PrintJob:
    """Pieces of ``placements`` (placed ones) as print outlines; the whole marker shows the fabric too.
    ``watermark``: the project's logo / word on the pieces (when it is switched on)."""
    from .. import watermark as W
    pcs = {p.uid: p for p in project.pieces}
    cfg = W.settings(project)
    art = None
    if watermark and W.active(cfg):
        from .watermark_art import art_for
        art = art_for(cfg)
        art = art if art.ok else None
    marks = []
    out = []
    for pl in placements:
        pc = pcs.get(pl.piece_uid)
        if not pl.placed or pc is None or pl.size not in pc.sizes:
            continue
        pts = placement_points(pc.sizes[pl.size].cut, pl)
        out.append((pts, f"{pc.name}  {pl.size.split(':', 1)[-1]}"))
        if art is not None:
            c = W.placement_corners(pc, pl, cfg, art.aspect)
            if c is not None:
                marks.append(c)
    whole = len(placements) == len(marker.placements)
    if whole:
        L = max([marker.length or 0.0] + [bbox(p)[2] for p, _ in out])
        world = (0.0, 0.0, L, marker.fabric.width)
        fabric = (L, marker.fabric.width)
    else:
        bs = [bbox(p) for p, _ in out] or [(0, 0, 1, 1)]
        world = (min(b[0] for b in bs) - 10, min(b[1] for b in bs) - 10,
                 max(b[2] for b in bs) + 10, max(b[3] for b in bs) + 10)
        fabric = None
    return PrintJob(out, world, fabric, title, info, marks=marks, art=art, **kw)


def setup_printer(printer: QPrinter, job: PrintJob) -> None:
    w, h = job.world[2] - job.world[0], job.world[3] - job.world[1]
    orient = job.orientation
    if orient == "auto":
        orient = "landscape" if w >= h else "portrait"
    layout = QPageLayout(QPageSize(PAPERS.get(job.paper, QPageSize.A4)),
                         QPageLayout.Landscape if orient == "landscape" else QPageLayout.Portrait,
                         QMarginsF(5, 5, 5, 5), QPageLayout.Millimeter)
    printer.setPageLayout(layout)


def _area_mm(printer: QPrinter) -> tuple[float, float]:
    """Drawing area (mm) of a page: paintable rect minus header and margins."""
    r = printer.pageLayout().paintRect(QPageLayout.Millimeter)
    return r.width() - 2 * MARGIN_MM, r.height() - 2 * MARGIN_MM - HEADER_MM


def tiles(printer: QPrinter, job: PrintJob) -> tuple[int, int, float]:
    """(columns, rows, scale paper-mm per marker-mm) of the job on this printer's paper."""
    aw, ah = _area_mm(printer)
    w, h = job.world[2] - job.world[0], job.world[3] - job.world[1]
    if not job.real_size:
        return 1, 1, min(aw / max(w, 1e-6), ah / max(h, 1e-6))
    step_w, step_h = aw - OVERLAP_MM, ah - OVERLAP_MM
    return max(1, math.ceil((w - OVERLAP_MM) / step_w)), max(1, math.ceil((h - OVERLAP_MM) / step_h)), 1.0


def page_count(printer: QPrinter, job: PrintJob) -> int:
    c, r, _ = tiles(printer, job)
    return c * r


def paint(printer: QPrinter, job: PrintJob) -> int:
    """Draw every page of the job on ``printer``; returns the number of pages."""
    cols, rows, scale = tiles(printer, job)
    aw, ah = _area_mm(printer)
    p = QPainter(printer)
    if not p.isActive():
        return 0
    try:
        page_px = printer.pageLayout().paintRectPixels(printer.resolution())
        mm = page_px.width() / printer.pageLayout().paintRect(QPageLayout.Millimeter).width()   # px per paper mm
        n = cols * rows
        k = 0
        for row in range(rows):                       # row 0 = top of the marker (highest y)
            for col in range(cols):
                if k:
                    printer.newPage()
                k += 1
                if job.real_size:
                    step_w, step_h = aw - OVERLAP_MM, ah - OVERLAP_MM
                    wx0 = job.world[0] + col * step_w
                    wy1 = job.world[3] - row * step_h
                    window = (wx0, wy1 - ah, wx0 + aw, wy1)
                else:
                    window = job.world
                _page(p, job, window, scale, mm, aw, ah, k, n, col, row, cols, rows)
    finally:
        p.end()
    return cols * rows


def _page(p, job, window, scale, mm, aw, ah, k, n, col, row, cols, rows):
    wx0, wy0, wx1, wy1 = window
    ox, oy = MARGIN_MM, MARGIN_MM + HEADER_MM                  # drawing area origin on the paper (mm)
    # header
    p.setPen(QPen(QColor(0, 0, 0)))
    f = QFont("Segoe UI", 9)
    f.setBold(True)
    p.setFont(f)
    date = datetime.date.today().isoformat()
    sc = "1:1" if job.real_size else f"1:{1 / scale:.0f}" if scale < 1 else f"{scale:.2f}:1"
    head = f"{job.title}    {job.info}    {sc}    {date}" + (f"    {k}/{n}" if n > 1 else "")
    p.drawText(QRectF(ox * mm, MARGIN_MM * mm, aw * mm, (HEADER_MM - 2) * mm), Qt.AlignLeft | Qt.AlignVCenter, head)
    if n > 1:
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(ox * mm, MARGIN_MM * mm, aw * mm, (HEADER_MM - 2) * mm), Qt.AlignRight | Qt.AlignVCenter,
                   f"column {col + 1}/{cols}   row {row + 1}/{rows}")
    p.save()
    clip = QRectF(ox * mm, oy * mm, aw * mm, ah * mm)
    p.setClipRect(clip)
    s = scale * mm                                              # px per marker mm

    def to_px(x, y):                                            # marker y up -> paper y down
        return QPointF((ox + (x - wx0) * scale) * mm, (oy + (wy1 - y) * scale) * mm)
    if job.fabric is not None:
        L, W = job.fabric
        p.setPen(QPen(QColor(120, 120, 120), max(1.0, 0.3 * mm), Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(to_px(0, W), to_px(L, 0)))
    shown = []
    for pts, label in job.pieces:
        b = bbox(pts)
        if b[2] < wx0 or b[0] > wx1 or b[3] < wy0 or b[1] > wy1:
            continue
        shown.append((b, label))
        poly = QPolygonF([to_px(x, y) for x, y in pts])
        path = QPainterPath()
        path.addPolygon(poly)
        path.closeSubpath()
        p.setBrush(QColor(235, 235, 235) if job.fill else Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0), max(1.0, 0.25 * mm)))
        p.drawPath(path)
    if job.art is not None:                                     # watermark: over the fill, under the names
        for tl, tr, bl in job.marks:
            xs = (tl[0], tr[0], bl[0], tr[0] + bl[0] - tl[0])
            ys = (tl[1], tr[1], bl[1], tr[1] + bl[1] - tl[1])
            if max(xs) < wx0 or min(xs) > wx1 or max(ys) < wy0 or min(ys) > wy1:
                continue
            a, b, c = (to_px(*q) for q in (tl, tr, bl))
            job.art.draw(p, (a.x(), a.y()), (b.x(), b.y()), (c.x(), c.y()))
    font = QFont("Segoe UI")
    for b, label in shown if job.names else ():
        w_px, h_px = (b[2] - b[0]) * s, (b[3] - b[1]) * s
        size = max(4.0, min(10.0, min(w_px, h_px) / mm / 3.5))            # points, fits small pieces
        font.setPointSizeF(size)
        p.setFont(font)
        c = to_px((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        p.setPen(QPen(QColor(40, 40, 40)))
        p.drawText(QRectF(c.x() - w_px / 2, c.y() - h_px / 2, w_px, h_px), Qt.AlignCenter | Qt.TextWordWrap, label)
    p.restore()
    p.setPen(QPen(QColor(0, 0, 0), max(1.0, 0.2 * mm)))
    p.setBrush(Qt.NoBrush)
    p.drawRect(clip)
    if job.real_size and n > 1:                                 # registration marks in the glue strips
        p.setPen(QPen(QColor(200, 0, 0), max(1.0, 0.25 * mm)))
        for x in ([ox + aw - OVERLAP_MM] if col < cols - 1 else []) + ([ox + OVERLAP_MM] if col > 0 else []):
            p.drawLine(QPointF(x * mm, oy * mm), QPointF(x * mm, (oy + ah) * mm))
        for y in ([oy + ah - OVERLAP_MM] if row < rows - 1 else []) + ([oy + OVERLAP_MM] if row > 0 else []):
            p.drawLine(QPointF(ox * mm, y * mm), QPointF((ox + aw) * mm, y * mm))
