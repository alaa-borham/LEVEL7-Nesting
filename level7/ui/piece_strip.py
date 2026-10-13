"""GRAFIS-like piece strip above the marker: one row per size/bundle, a to-scale outline of every piece type,
and the copies still to place (normal / mirrored, "-" = no mirrored copies) under each outline."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QScrollArea, QToolTip, QWidget

from ..geometry import bbox, transform_points
from .marker_view import bundle_letter

THUMB_H = 26          # px available for the outline (compact: more room for the marker)
ROW_H = THUMB_H + 18  # outline + count line
HEAD_W = 54           # size / bundle column (minimum; grows for "model:size" names)
TOP = 14              # "Pc: placed/total" line
MIN_CELL = 56
MAX_CELL = 150


CHECK = 12            # include / exclude check box in the size column


class PieceStrip(QWidget):
    open_table = Signal()
    row_toggled = Signal(str, int)      # (size, bundle): include / exclude this row from the marker

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setLayoutDirection(Qt.LeftToRight)     # GRAFIS layout: sizes on the left, counts "n  m"
        self.rows: list[tuple[str, int]] = []
        self.cols = []            # (piece, cell_x, cell_w)
        self.counts = {}          # (row, piece_uid) -> (rem_n, rem_m, has_m)
        self.shapes = {}          # (size, piece_uid) -> outline points in strip mm, origin at its bbox centre
        self.scale = 1.0
        self.placed = self.total = 0

    # -- data ------------------------------------------------------------------------------
    def set_data(self, project, marker):
        from ..service import model_tags
        self.tags = model_tags(project) if project is not None else []
        self.rows, self.cols, self.counts, self.shapes = [], [], {}, {}
        self.placed = self.total = 0
        if project is None:
            self.updateGeometry()
            self.update()
            return
        co = project.cut_order
        self.excluded = {(s, int(b)) for s, b in (getattr(co, "excluded", None) or [])}
        pcs = {p.uid: p for p in project.pieces}
        groups: dict[tuple[str, int, str], list] = {}
        marker_rows: set = set()
        if marker is not None and marker.placements:
            for pl in marker.placements:
                groups.setdefault((pl.size, pl.bundle, pl.piece_uid), []).append(pl)
            self.placed = sum(1 for pl in marker.placements if pl.placed)
            self.total = len(marker.placements)
            marker_rows = {(k[0], k[1]) for k in groups}
        # sizes / quantities chosen in the cut order show up at once (still to place), like GRAFIS
        order_rows = {(s, b) for s, q in co.size_quantities.items() for b in range(1, (q or 0) + 1)}
        self.rows = sorted(marker_rows | order_rows, key=lambda r: (_size_key(r[0]), r[1]))
        used = {k[2] for k in groups} | {u for u, (n, m) in co.piece_counts.items() if n + m > 0}
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
                elif (size, b) in marker_rows or n + m == 0 or size not in p.sizes \
                        or (p.model and not size.startswith(p.model + ":")):
                    continue
                else:
                    rn, rm, has_m = n, m, m > 0
                    if (size, b) not in self.excluded:
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
        from PySide6.QtGui import QFontMetrics
        f = QFont(self.font())
        f.setPointSizeF(8)
        fm = QFontMetrics(f)
        from ..service import size_label
        self.head_w = CHECK + 6 + min(220, max(HEAD_W, max((fm.horizontalAdvance(size_label(self.tags, sz)) + 26
                                                for sz, _b in self.rows), default=0)))
        x = self.head_w
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
        p.setLayoutDirection(Qt.LeftToRight)
        p.fillRect(self.rect(), bg)
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(fg)
        legend = "    ".join(f"{k + 1} = {t}" for k, t in enumerate(getattr(self, "tags", [])))
        p.drawText(QPointF(4, 11), f"Pc: {self.placed}/ {self.total}" + (f"      {legend}" if legend else ""))
        hw = getattr(self, "head_w", HEAD_W)
        p.drawLine(hw - 4, TOP, hw - 4, self.height())
        dim = QColor(fg)
        dim.setAlpha(140)
        for r, (size, b) in enumerate(self.rows):
            y = TOP + r * ROW_H
            off = (size, b) in getattr(self, "excluded", set())
            # include / exclude check box
            box = QRectF(3, y + (ROW_H - CHECK) / 2, CHECK, CHECK)
            p.setPen(QPen(fg, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(box)
            if not off:
                p.setPen(QPen(QColor(0, 150, 60), 2.0))
                p.drawLine(QPointF(box.left() + 2.5, box.center().y()), QPointF(box.left() + 5, box.bottom() - 2.5))
                p.drawLine(QPointF(box.left() + 5, box.bottom() - 2.5), QPointF(box.right() - 2, box.top() + 2.5))
            p.setPen(dim if off else fg)
            from ..service import size_label
            tx = CHECK + 8
            p.drawText(QRectF(tx, y + 2, hw - 8 - tx, ROW_H - 4), Qt.AlignLeft | Qt.AlignVCenter,
                       size_label(self.tags, size))
            p.drawText(QRectF(tx, y + 2, hw - 8 - tx, ROW_H - 4), Qt.AlignRight | Qt.AlignVCenter,
                       bundle_letter(b))
            p.setPen(QPen(dim, 1))
            p.drawLine(0, y + ROW_H, self.width(), y + ROW_H)
            for piece, x, cw in self.cols:
                c = self.counts.get(((size, b), piece.uid))
                shape = self.shapes.get((size, piece.uid))
                if c is None:
                    continue
                rn, rm, has_m = c
                done = (rn == 0 and rm == 0) or off
                if shape:
                    cx, cy = x + cw / 2, y + 3 + THUMB_H / 2
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
                p.drawText(QRectF(x, y + ROW_H - 15, cw, 14), Qt.AlignCenter, txt)
        p.end()

    def _piece_at(self, pos):
        for piece, x, cw in self.cols:
            if x <= pos.x() < x + cw:
                return piece
        return None

    def mouseMoveEvent(self, ev):
        if ev.position().x() < getattr(self, "head_w", HEAD_W) and self._row_at(ev.position()) is not None:
            from .i18n import tr
            QToolTip.showText(ev.globalPosition().toPoint(), tr("strip_toggle_tip"), self)
            return
        pc = self._piece_at(ev.position())
        if pc is not None:
            num = f"{pc.number:03d}" if pc.number is not None else "—"
            QToolTip.showText(ev.globalPosition().toPoint(), f"{num}: {pc.name}", self)
        else:
            QToolTip.hideText()

    def _row_at(self, pos):
        r = int((pos.y() - TOP) // ROW_H)
        return self.rows[r] if pos.y() >= TOP and 0 <= r < len(self.rows) else None

    def mousePressEvent(self, ev):
        row = self._row_at(ev.position())
        if row is not None and ev.button() == Qt.LeftButton and ev.position().x() < getattr(self, "head_w", HEAD_W):
            self.row_toggled.emit(row[0], row[1])
            return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.position().x() < getattr(self, "head_w", HEAD_W):
            return                                       # a quick second click on the box just toggles again
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
    area.setLayoutDirection(Qt.LeftToRight)
    return area, strip
