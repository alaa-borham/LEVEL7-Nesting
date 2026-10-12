"""Toolbar icons drawn in code (no image files): crisp at any DPI, adapted to light and dark themes."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

ACCENT = QColor(240, 160, 10)      # LEVEL7 / GRAFIS piece colour
GREEN, RED, BLUE = QColor(40, 170, 80), QColor(215, 60, 50), QColor(40, 120, 220)


def _fg() -> QColor:
    return QApplication.instance().palette().color(QPalette.WindowText)


def _arrow_head(p: QPainter, tip: QPointF, angle: float, size: float = 6.0):
    a = math.radians(angle)
    pts = [tip, QPointF(tip.x() - size * math.cos(a - 0.5), tip.y() - size * math.sin(a - 0.5)),
           QPointF(tip.x() - size * math.cos(a + 0.5), tip.y() - size * math.sin(a + 0.5))]
    p.setBrush(p.pen().color())
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(Qt.NoBrush)


def _piece(p: QPainter, r: QRectF, fill=ACCENT):
    """Small pattern-piece outline (trouser-like), used by several icons."""
    path = QPainterPath()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    path.moveTo(x, y + h * 0.15)
    path.cubicTo(x + w * 0.4, y, x + w * 0.7, y + h * 0.05, x + w, y)
    path.lineTo(x + w * 0.9, y + h * 0.7)
    path.cubicTo(x + w * 0.75, y + h * 0.75, x + w * 0.6, y + h, x + w * 0.5, y + h)
    path.lineTo(x, y + h * 0.85)
    path.closeSubpath()
    c = QColor(fill)
    c.setAlpha(200)
    p.setBrush(c)
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)


def _draw(name: str, p: QPainter, fg: QColor):
    pen = QPen(fg, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    if name == "open":
        p.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 170))
        p.drawPolygon(QPolygonF([QPointF(3, 9), QPointF(12, 9), QPointF(15, 12), QPointF(29, 12),
                                 QPointF(29, 27), QPointF(3, 27)]))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(16, 23), QPointF(16, 15))
        _arrow_head(p, QPointF(16, 14), -90, 5)
    elif name == "save":
        p.drawRoundedRect(QRectF(5, 5, 22, 22), 2, 2)
        p.drawRect(QRectF(10, 5, 12, 7))
        p.setBrush(QColor(BLUE.red(), BLUE.green(), BLUE.blue(), 150))
        p.drawRect(QRectF(9, 17, 14, 10))
        p.setBrush(Qt.NoBrush)
    elif name in ("undo", "redo"):
        sgn = -1 if name == "undo" else 1
        path = QPainterPath()
        cx = 16
        path.moveTo(cx - sgn * 9, 24)
        path.cubicTo(cx - sgn * 12, 12, cx + sgn * 2, 7, cx + sgn * 9, 13)
        p.drawPath(path)
        _arrow_head(p, QPointF(cx + sgn * 11, 15), 45 if sgn > 0 else 135, 6)
    elif name == "rotate180":
        _piece(p, QRectF(9, 10, 14, 12))
        p.setPen(QPen(BLUE, 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(3, 3, 26, 26), 30 * 16, 150 * 16)
        p.drawArc(QRectF(3, 3, 26, 26), 210 * 16, 150 * 16)
        _arrow_head(p, QPointF(4.5, 11), 110, 5)
        _arrow_head(p, QPointF(27.5, 21), -70, 5)
    elif name == "pin":
        p.setBrush(RED)
        p.drawEllipse(QRectF(10, 4, 12, 12))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(16, 16), QPointF(16, 29))
        p.drawLine(QPointF(10, 16), QPointF(22, 16))
    elif name == "measure":
        p.save()
        p.translate(16, 16)
        p.rotate(-35)
        p.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 150))
        p.drawRect(QRectF(-14, -5, 28, 10))
        p.setBrush(Qt.NoBrush)
        for i in range(-10, 12, 4):
            p.drawLine(QPointF(i, -5), QPointF(i, -1 if i % 8 else 1))
        p.restore()
    elif name == "zoom_fit":
        p.drawEllipse(QRectF(5, 5, 16, 16))
        p.drawLine(QPointF(19, 19), QPointF(28, 28))
        for (x, y, dx, dy) in ((9, 9, 3, 3), (17, 9, -3, 3), (9, 17, 3, -3), (17, 17, -3, -3)):
            p.drawLine(QPointF(x, y + dy), QPointF(x, y))
            p.drawLine(QPointF(x, y), QPointF(x + dx, y))
    elif name == "display":
        p.drawRoundedRect(QRectF(3, 6, 26, 20), 3, 3)
        _piece(p, QRectF(7, 10, 11, 11))
        p.setBrush(fg)
        for y in (11, 16, 21):
            p.drawEllipse(QPointF(23, y), 1.6, 1.6)
        p.setBrush(Qt.NoBrush)
    elif name == "run":
        p.setPen(Qt.NoPen)
        p.setBrush(GREEN)
        p.drawEllipse(QRectF(3, 3, 26, 26))
        p.setBrush(QColor("white"))
        p.drawPolygon(QPolygonF([QPointF(12, 9), QPointF(23, 16), QPointF(12, 23)]))
    elif name == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawEllipse(QRectF(3, 3, 26, 26))
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(11, 11, 10, 10))
    elif name in ("plt", "dxf", "iso"):
        p.drawPolygon(QPolygonF([QPointF(6, 3), QPointF(21, 3), QPointF(27, 9), QPointF(27, 29), QPointF(6, 29)]))
        p.drawPolyline(QPolygonF([QPointF(21, 3), QPointF(21, 9), QPointF(27, 9)]))
        col = {"plt": BLUE, "dxf": GREEN, "iso": RED}[name]
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(2, 15, 24, 10), 2, 2)
        p.setPen(QColor("white"))
        f = QFont()
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(2, 15, 24, 10), Qt.AlignCenter, name.upper())
    elif name == "language":
        p.drawEllipse(QRectF(4, 4, 24, 24))
        p.drawEllipse(QRectF(10, 4, 12, 24))
        p.drawLine(QPointF(4, 16), QPointF(28, 16))
        p.drawLine(QPointF(6, 10), QPointF(26, 10))
        p.drawLine(QPointF(6, 22), QPointF(26, 22))
    elif name == "pieces":
        for i, x in enumerate((3, 12, 21)):
            _piece(p, QRectF(x, 9, 8, 14 - i * 3))


def icon(name: str) -> QIcon:
    ic = QIcon()
    fg = _fg()
    for size in (32, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 32.0, size / 32.0)
        _draw(name, p, fg)
        p.end()
        ic.addPixmap(pm)
    return ic
