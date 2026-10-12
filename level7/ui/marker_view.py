"""Marker canvas: QGraphicsView with real-unit (mm) scene, Y axis up, rulers,
zoom/pan, selection, drag-move, measure tool."""
from __future__ import annotations

import colorsys
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from ..geometry import placement_points


def _path(points, closed=True) -> QPainterPath:
    p = QPainterPath()
    if not points:
        return p
    p.moveTo(*points[0])
    for x, y in points[1:]:
        p.lineTo(x, y)
    if closed:
        p.closeSubpath()
    return p


def color_for(key: str) -> QColor:
    h = (abs(hash(key)) % 997) / 997.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.35, 0.95)
    return QColor(int(r * 255), int(g * 255), int(b * 255), 210)


class PieceItem(QGraphicsPathItem):
    def __init__(self, view, placement, piece):
        super().__init__()
        self.view = view
        self.placement = placement
        self.piece = piece
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, not placement.pinned)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.children_items = []
        self.label = None
        self.rebuild()

    def rebuild(self):
        for c in self.children_items:
            self.scene().removeItem(c) if c.scene() else None
        self.children_items = []
        pl, g = self.placement, self.piece.sizes[self.placement.size]
        self.setPos(0, 0)
        self.setPath(_path(placement_points(g.cut, pl)))
        opts = self.view.options
        if opts["seam"]:
            for s in g.seam:
                self._child(placement_points(s.points, pl), s.closed, QPen(QColor(0, 110, 0), 0, Qt.DashLine))
        if opts["internal"]:
            for s in g.internal:
                self._child(placement_points(s.points, pl), False, QPen(QColor(120, 120, 120), 0))
            for n in g.notches:
                d = n.direction or (0, 0)
                pts = [n.position, (n.position[0] + d[0] * n.length, n.position[1] + d[1] * n.length)]
                self._child(placement_points(pts, pl), False, QPen(QColor(200, 0, 0), 0))
        if opts["grain"] and g.grain is not None:
            self._child(placement_points(g.grain.points, pl), False, QPen(QColor(0, 0, 200), 0))
        if opts["labels"]:
            from shapely.geometry import Polygon
            c = Polygon(placement_points(g.cut, pl)).representative_point()
            t = QGraphicsSimpleTextItem(f"{self.piece.name} {pl.size}{' M' if pl.mirrored else ''}", self)
            t.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            t.setFont(QFont("Segoe UI", 8))
            t.setPos(c.x, c.y)
            self.children_items.append(t)
        self.restyle()

    def _child(self, pts, closed, pen):
        it = QGraphicsPathItem(_path(pts, closed), self)
        it.setPen(pen)
        it.setAcceptedMouseButtons(Qt.NoButton)
        self.children_items.append(it)

    def restyle(self):
        key = self.placement.size if self.view.options["color_by"] == "size" else self.piece.uid
        col = color_for(key)
        bad = self.placement.uid in self.view.bad
        if bad:
            col = QColor(255, 60, 60, 200)
        self.setBrush(QBrush(col))
        pen = QPen(QColor(0, 0, 0), 0)
        if self.placement.pinned:
            pen = QPen(QColor(30, 30, 160), 0, Qt.DashDotLine)
        self.setPen(pen)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        d = self.pos()
        if abs(d.x()) > 1e-9 or abs(d.y()) > 1e-9:
            self.view.moved.emit([(it.placement, it.pos().x(), it.pos().y())
                                  for it in self.scene().selectedItems() if isinstance(it, PieceItem)] or
                                 [(self.placement, d.x(), d.y())])


class MarkerView(QGraphicsView):
    moved = Signal(list)           # [(placement, dx, dy)]
    cursor_mm = Signal(float, float)
    measured = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setTransform(QTransform.fromScale(0.3, -0.3))
        self.options = {"seam": False, "internal": False, "grain": True, "labels": True, "color_by": "size"}
        self.bad: set[str] = set()
        self.items_by_uid: dict[str, PieceItem] = {}
        self.project = None
        self.marker = None
        self.measure_mode = False
        self._measure_pts: list[QPointF] = []
        self._measure_item = None
        self._pan = None

    def show_marker(self, project, marker, bad=None):
        self.project, self.marker = project, marker
        self.bad = set(bad or [])
        sc = self.scene()
        sc.clear()
        self.items_by_uid = {}
        if marker is None:
            return
        L = max(marker.length, 100.0)
        W = marker.fabric.width
        sc.addRect(QRectF(0, 0, L, W), QPen(QColor(60, 60, 60), 0), QBrush(QColor(250, 250, 245)))
        f = marker.fabric
        if f.margin_left or f.margin_right or f.lay_type.value == "folded":
            r = QRectF(f.margin_start, f.margin_left, L - f.margin_start, f.usable_width)
            sc.addRect(r, QPen(QColor(150, 150, 220), 0, Qt.DashLine))
        for pl in marker.placements:
            if not pl.placed:
                continue
            it = PieceItem(self, pl, project.piece(pl.piece_uid))
            sc.addItem(it)
            it.rebuild()
            self.items_by_uid[pl.uid] = it
        sc.setSceneRect(QRectF(-200, -200, L + 400, W + 400))

    def refresh(self, bad=None):
        if bad is not None:
            self.bad = set(bad)
        for it in self.items_by_uid.values():
            it.setFlag(QGraphicsItem.ItemIsMovable, not it.placement.pinned)
            it.rebuild()

    def zoom_fit(self):
        if self.marker:
            self.fitInView(QRectF(-50, -50, max(self.marker.length, 100) + 100, self.marker.fabric.width + 100),
                           Qt.KeepAspectRatio)
            t = self.transform()
            self.setTransform(QTransform(t.m11(), 0, 0, -abs(t.m22()), 0, 0))
            self.centerOn(max(self.marker.length, 100) / 2, self.marker.fabric.width / 2)

    def selected_placements(self):
        return [it.placement for it in self.scene().selectedItems() if isinstance(it, PieceItem)]

    # -- interaction -----------------------------------------------------------------
    def wheelEvent(self, ev):
        f = 1.25 if ev.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self._pan = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.measure_mode and ev.button() == Qt.LeftButton:
            p = self.mapToScene(ev.position().toPoint())
            self._measure_pts.append(p)
            if len(self._measure_pts) == 2:
                a, b = self._measure_pts
                d = math.hypot(b.x() - a.x(), b.y() - a.y())
                if self._measure_item:
                    self.scene().removeItem(self._measure_item)
                self._measure_item = self.scene().addLine(a.x(), a.y(), b.x(), b.y(), QPen(QColor(255, 0, 255), 0))
                self._measure_pts = []
                self.measured.emit(d)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._pan is not None:
            d = ev.position() - self._pan
            self._pan = ev.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        p = self.mapToScene(ev.position().toPoint())
        self.cursor_mm.emit(p.x(), p.y())
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self._pan = None
            self.setCursor(Qt.ArrowCursor)
            return
        super().mouseReleaseEvent(ev)

    # -- rulers ------------------------------------------------------------------------
    def drawForeground(self, painter: QPainter, rect: QRectF):
        painter.save()
        painter.resetTransform()
        vw, vh = self.viewport().width(), self.viewport().height()
        painter.fillRect(0, 0, vw, 18, QColor(240, 240, 240, 230))
        painter.fillRect(0, 0, 40, vh, QColor(240, 240, 240, 230))
        painter.setPen(QColor(60, 60, 60))
        painter.setFont(QFont("Segoe UI", 7))
        scale = abs(self.transform().m11())
        step = 10.0
        for s in (10, 20, 50, 100, 200, 500, 1000, 2000):
            if s * scale >= 60:
                step = s
                break
        x0 = self.mapToScene(0, 0).x()
        x1 = self.mapToScene(vw, 0).x()
        v = math.floor(x0 / step) * step
        while v <= x1:
            px = self.mapFromScene(QPointF(v, 0)).x()
            painter.drawLine(px, 12, px, 18)
            painter.drawText(px + 2, 11, f"{v:g}")
            v += step
        ya = self.mapToScene(0, vh).y()
        yb = self.mapToScene(0, 0).y()
        v = math.floor(min(ya, yb) / step) * step
        while v <= max(ya, yb):
            py = self.mapFromScene(QPointF(0, v)).y()
            painter.drawLine(34, py, 40, py)
            painter.drawText(2, py - 2, f"{v:g}")
            v += step
        painter.drawText(44, 11, "mm")
        painter.restore()


_ = QPolygonF
