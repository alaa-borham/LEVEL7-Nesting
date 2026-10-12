"""GRAFIS-like piece strip above the marker: one row per size/bundle, a to-scale outline of every piece type,
and the copies still to place (normal / mirrored, "-" = no mirrored copies) under each outline."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QScrollArea, QToolTip, QWidget

from ..geometry import bbox, transform_points
from .marker_view import bundle_letter

THUMB_H = 52          # px available for the outline
ROW_H = THUMB_H + 30  # outline + count line
HEAD_W = 54           # size / bundle column
TOP = 18              # "Pc: placed/total" line
MIN_CELL = 56
MAX_CELL = 190


class PieceStrip(QWidget):
    open_table = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.rows: list[tuple[str, int]] = []
        self.cols = []            # (piece, cell_x, cell_w)
        self.counts = {}          # (row, piece_uid) -> (rem_n, rem_m, has_m)
        self.shapes = {}          # (size, piece_uid) -> outline points in strip mm, origin at its bbox centre
        self.scale = 1.0
        self.placed = self.total = 0

    # -- data ------------------------------------------------------------------------------
    def set_data(self, project, marker):
        self.rows, self.cols, self.counts, self.shapes = [], [], {}, {}
        self.placed = self.total = 0
        if project is None:
            self.updateGeometry()
            self.update()
            return
        co = project.cut_order
        pcs = {p.uid: p for p in project.pieces}
        groups: dict[tuple[str, int, str], list] = {}
        if marker is not None and marker.placements:
            for pl in marker.placements:
                groups.setdefault((pl.size, pl.bundle, pl.piece_uid), []).append(pl)
            self.placed = sum(1 for pl in marker.placements if pl.placed)
            self.total = len(marker.placements)
            self.rows = sorted({(k[0], k[1]) for k in groups}, key=lambda r: (_size_key(r[0]), r[1]))
            used = {k[2] for k in groups}
        else:                    # project only: rows from the cut order, nothing placed yet
            for s, q in sorted(co.size_quantities.items(), key=lambda x: _size_key(x[0])):
                for b in range(1, q + 1):
                    self.rows.append((s, b))
            used = {u for u, (n, m) in co.piece_counts.items() if n + m > 0}
        pieces = [p for p in project.pieces if p.uid in used]
        pieces.sort(key=lambda p: (p.number if p.number is not None else 10 ** 6, p.name))
        for (size, b) in self.rows:
            for p in pieces:
                n, m = co.piece_counts.get(p.uid, (p.default_count, p.default_mirrored))
                pls = groups.get((size, b, p.uid))
                if pls is not None:
                    rn = sum(1 for pl in pls if not pl.placed and not pl.mirrored)
                    rm = sum(1 for pl in pls if not pl.placed and pl.mirrored)
                    has_m = m > 0 or any(pl.mirrored for pl in pls)
                elif marker is not None and marker.placements:
                    continue
                else:
                    rn, rm, has_m = n, m, m > 0
                    self.total += n + m
                self.counts[((size, b), p.uid)] = (rn, rm, has_m)
        # outlines turned so the grain runs along the strip, all at one scale
        maxw = maxh = 1.0
        for (size, _b) in self.rows:
            for p in pieces:
                g = p.sizes.get(size) or next(iter(p.sizes.values()), None)
                if g is None or (size, p.uid) in self.shapes:
                    continue
                rot = -(p.grain_angle or 0.0)
                pts = transform_points(g.cut, rot, False)
                x0, y0, x1, y1 = bbox(pts)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                self.shapes[(size, p.uid)] = [(x - cx, y - cy) for x, y in pts]
                maxw, maxh = max(maxw, x1 - x0), max(maxh, y1 - y0)
        self.scale = min((MAX_CELL - 16) / maxw, THUMB_H / maxh)
        x = HEAD_W
        for p in pieces:
            w = max((bbox(s)[2] - bbox(s)[0] for (sz, u), s in self.shapes.items() if u == p.uid), default=0)
            cw = int(max(MIN_CELL, w * self.scale + 24))
            self.cols.append((p, x, cw))
            x += cw
        self.updateGeometry()
        self.resize(self.sizeHint())
        self.update()

    def sizeHint(self):
        w = (self.cols[-1][1] + self.cols[-1][2] + 8) if self.cols else 200
        return QSize(w, TOP + max(1, len(self.rows)) * ROW_H + 4)

    minimumSizeHint = sizeHint

    # -- painting ----------------------------------------------------------------------------
    def paintEvent(self, ev):
        pal = self.palette()
        fg, bg = pal.color(QPalette.WindowText), pal.color(QPalette.Base)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), bg)
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(QPointF(4, 13), f"Pc: {self.placed}/ {self.total}")
        p.drawLine(HEAD_W - 4, TOP, HEAD_W - 4, self.height())
        dim = QColor(fg)
        dim.setAlpha(140)
        for r, (size, b) in enumerate(self.rows):
            y = TOP + r * ROW_H
            p.setPen(fg)
            p.drawText(QRectF(2, y + ROW_H - 18, HEAD_W - 8, 16), Qt.AlignLeft | Qt.AlignVCenter, size)
            p.drawText(QRectF(2, y + ROW_H - 18, HEAD_W - 8, 16), Qt.AlignRight | Qt.AlignVCenter, bundle_letter(b))
            p.setPen(QPen(dim, 1))
            p.drawLine(0, y + ROW_H, self.width(), y + ROW_H)
            for piece, x, cw in self.cols:
                c = self.counts.get(((size, b), piece.uid))
                shape = self.shapes.get((size, piece.uid))
                if c is None:
                    continue
                rn, rm, has_m = c
                done = rn == 0 and rm == 0
                if shape:
                    cx, cy = x + cw / 2, y + 4 + THUMB_H / 2
                    path = QPainterPath()
                    for i, (sx, sy) in enumerate(shape):
                        pt = QPointF(cx + sx * self.scale, cy - sy * self.scale)
                        path.moveTo(pt) if i == 0 else path.lineTo(pt)
                    path.closeSubpath()
                    p.setPen(QPen(dim if done else fg, 1.2))
                    if not done:
                        p.setBrush(QColor(240, 160, 10, 90))
                    p.drawPath(path)
                    p.setBrush(Qt.NoBrush)
                p.setPen(fg if not done else dim)
                txt = f"{rn}   {rm if has_m else '-'}"
                p.drawText(QRectF(x, y + ROW_H - 18, cw, 16), Qt.AlignCenter, txt)
        p.end()

    def _piece_at(self, pos):
        for piece, x, cw in self.cols:
            if x <= pos.x() < x + cw:
                return piece
        return None

    def mouseMoveEvent(self, ev):
        pc = self._piece_at(ev.position())
        if pc is not None:
            num = f"{pc.number:03d}" if pc.number is not None else "—"
            QToolTip.showText(ev.globalPosition().toPoint(), f"{num}: {pc.name}", self)
        else:
            QToolTip.hideText()

    def mouseDoubleClickEvent(self, ev):
        self.open_table.emit()


def _size_key(s: str):
    import re
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    order = {"XXS": 0, "XS": 1, "S": 2, "M": 3, "L": 4, "XL": 5, "2XL": 6, "XXL": 6, "3XL": 7, "XXXL": 7,
             "4XL": 8, "5XL": 9}
    head = (s or "").split("-")[0].upper()
    return (order.get(head, 50), float(m.group()) if m and head not in order else 0.0, s)


def make_strip_area(parent=None):
    strip = PieceStrip()
    area = QScrollArea(parent)
    area.setWidget(strip)
    area.setWidgetResizable(True)       # fills the width; scrolls when the pieces need more room
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setFrameShape(QScrollArea.NoFrame)
    return area, strip
