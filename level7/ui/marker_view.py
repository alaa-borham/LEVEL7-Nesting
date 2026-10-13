"""Marker canvas: QGraphicsView with real-unit (mm) scene, Y axis up, rulers,
zoom/pan, selection, drag-move, measure tool."""
from __future__ import annotations

import colorsys
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from ..geometry import lay_direction, placement_points, transform_points


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
    import zlib
    h = (zlib.crc32(key.encode("utf-8")) % 997) / 997.0      # stable between runs (hash() is salted)
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.95)
    return QColor(int(r * 255), int(g * 255), int(b * 255), 210)


DEFAULT_OPTIONS = {
    # "Display in the pieces" (GRAFIS: Marker display options)
    "symbols": False, "size_bundle": True, "buffer": True, "marking": False, "grain": False, "internal": False,
    "piece_names": False, "direction": True, "view_rot90": False, "view_rot180": False,     # direction arrow (→ / ← = turned 180°) next to the label
    # "Display auxiliary objects"
    "efficiency_mark": True, "last_efficiency": True, "white_marking": True,
    # "Show pieces to be placed"
    "fill": "solid_outline",          # outline | solid | solid_outline
    "bg_opacity": 25, "piece_transparency": 50, "inverse_inner": False,
    "status_mm": False, "color_by": "bundle",   # bundle | size | piece
}

BUNDLE_COLOURS = [QColor(248, 190, 90), QColor(240, 160, 10), QColor(120, 190, 240), QColor(60, 140, 210),
                  QColor(150, 220, 140), QColor(80, 170, 90)]


def bundle_letter(n: int) -> str:
    s = ""
    n = max(1, n)
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


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
        self.rebuild()

    def _inner_colour(self, base: QColor) -> QColor:
        return QColor(255 - base.red(), 255 - base.green(), 255 - base.blue()) if self.view.options["inverse_inner"] \
            else base

    def rebuild(self):
        for c in self.children_items:
            self.scene().removeItem(c) if c.scene() else None
        self.children_items = []
        pl, g = self.placement, self.piece.sizes[self.placement.size]
        self.setPos(0, 0)
        cut = placement_points(g.cut, pl)
        self.setPath(_path(cut))
        o = self.view.options
        dark = QColor(40, 40, 40)
        if o["buffer"] and self.view.marker is not None and self.view.marker.fabric.spacing > 0:
            from shapely.geometry import Polygon
            buf = Polygon(cut).buffer(self.view.marker.fabric.spacing / 2.0, join_style=2)
            self._child(list(buf.exterior.coords), True, QPen(QColor(150, 150, 150), 0, Qt.DotLine))
        if o["internal"]:
            for s in g.seam:
                self._child(placement_points(s.points, pl), s.closed, QPen(self._inner_colour(QColor(0, 110, 0)), 0,
                                                                            Qt.DashLine))
            for s in g.internal:
                self._child(placement_points(s.points, pl), False, QPen(self._inner_colour(dark), 0))
        if o["marking"]:
            for n in g.notches:
                d = n.direction or (0, 0)
                pts = [n.position, (n.position[0] + d[0] * n.length, n.position[1] + d[1] * n.length)]
                self._child(placement_points(pts, pl), False, QPen(QColor(200, 0, 0), 0))
        if o["grain"] and g.grain is not None:
            gp = placement_points(g.grain.points, pl)
            pen = QPen(self._inner_colour(QColor(0, 0, 200)), 0)
            self._child(gp, False, pen)
            (ax, ay), (bx, by) = gp[0], gp[-1]
            if self.piece.grain_angle is not None:      # head on the same side as the label arrow (→ / ←)
                r = math.radians(self.piece.grain_angle)
                (ux, uy), = transform_points([(math.cos(r), math.sin(r))], pl.rotation, pl.mirrored)
                if (bx - ax) * ux + (by - ay) * uy < 0:
                    (ax, ay), (bx, by) = (bx, by), (ax, ay)
            L = math.hypot(bx - ax, by - ay)
            if L > 0:                      # arrowhead at the end of the grain line shows the lay direction
                ux, uy, h = (bx - ax) / L, (by - ay) / L, min(25.0, L / 4)
                for sgn in (1, -1):
                    self._child([(bx, by), (bx - h * ux + sgn * 0.4 * h * uy, by - h * uy - sgn * 0.4 * h * ux)],
                                False, pen)
        if o["symbols"]:
            for ms in g.measures:
                x, y = placement_points([ms.position], pl)[0]
                t = QGraphicsSimpleTextItem(ms.text, self)
                t.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                t.setFont(QFont("Segoe UI", 7))
                t.setBrush(QBrush(QColor(160, 0, 160)))
                t.setPos(x, y)
                t.setAcceptedMouseButtons(Qt.NoButton)
                self.children_items.append(t)
            for dr in g.drills:
                x, y = placement_points([dr.position], pl)[0]
                p = QPainterPath()
                p.moveTo(x - 4, y)
                p.lineTo(x + 4, y)
                p.moveTo(x, y - 4)
                p.lineTo(x, y + 4)
                p.addEllipse(QPointF(x, y), 3, 3)
                it = QGraphicsPathItem(p, self)
                it.setPen(QPen(QColor(160, 0, 160), 0))
                it.setAcceptedMouseButtons(Qt.NoButton)
                self.children_items.append(it)
        lines = []
        if o["size_bundle"]:
            arrow = ""
            d = lay_direction(self.piece.grain_angle, pl) if o.get("direction", True) else None
            arrow = ""
            if d is not None:      # arrow as seen on screen (the view may be rotated in the display options)
                v = self.view.base_transform().map(QPointF(float(d), 0.0))
                arrow = (" →" if v.x() > 0 else " ←") if abs(v.x()) >= abs(v.y()) else (" ↓" if v.y() > 0 else " ↑")
            from ..service import size_label
            lines.append(f"{size_label(self.view.model_tags, pl.size)}/{bundle_letter(pl.bundle)}{arrow}")
        if o["piece_names"]:
            lines.append(f"{self.piece.name}{' (M)' if pl.mirrored else ''}")
        if lines:
            from shapely.geometry import Polygon
            c = Polygon(cut).representative_point()
            t = QGraphicsSimpleTextItem("\n".join(lines), self)
            t.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            t.setFont(QFont("Segoe UI", 8))
            from .themes import CURRENT
            white = o["white_marking"] and CURRENT["name"] != "light"     # dark text on the light theme
            t.setBrush(QBrush(QColor(255, 255, 255) if white else QColor(20, 20, 20)))
            br = t.boundingRect()
            t.setPos(c.x, c.y)
            t.setTransform(QTransform.fromTranslate(-br.width() / 2, -br.height() / 2))
            t.setAcceptedMouseButtons(Qt.NoButton)
            self.children_items.append(t)
        self.restyle()

    def _child(self, pts, closed, pen):
        it = QGraphicsPathItem(_path(pts, closed), self)
        it.setPen(pen)
        it.setAcceptedMouseButtons(Qt.NoButton)
        self.children_items.append(it)

    def restyle(self):
        o = self.view.options
        if o["color_by"] == "bundle":
            col = QColor(BUNDLE_COLOURS[(self.placement.bundle - 1) % len(BUNDLE_COLOURS)])
        else:
            col = color_for(self.placement.size if o["color_by"] == "size" else self.piece.uid)
        if self.placement.uid in self.view.bad:
            col = QColor(255, 60, 60)
        # pieces are always clearly coloured against the fabric: transparency never goes below 60 % opacity,
        # and "outline only" draws the outline in the piece colour over a light tint of it
        base = QColor(col)
        col.setAlpha(int(255 * (1 - 0.4 * o["piece_transparency"] / 100.0)))
        if o["fill"] == "outline":
            tint = QColor(base)
            tint.setAlpha(60)
            self.setBrush(QBrush(tint))
        else:
            self.setBrush(QBrush(col))
        if self.placement.pinned:
            pen = QPen(QColor(30, 30, 160), 0, Qt.DashDotLine)
        elif o["fill"] == "solid":
            pen = QPen(Qt.NoPen)
        elif o["fill"] == "outline":
            pen = QPen(base, 2)
            pen.setCosmetic(True)
        else:
            pen = QPen(QColor(255, 255, 255) if o["white_marking"] else QColor(0, 0, 0), 0)
        self.setPen(pen)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.view is not None:
            self.view.dragging.emit()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        d = self.pos()
        if abs(d.x()) > 1e-9 or abs(d.y()) > 1e-9:
            self.view.moved.emit([(it.placement, it.pos().x(), it.pos().y())
                                  for it in self.scene().selectedItems() if isinstance(it, PieceItem)] or
                                 [(self.placement, d.x(), d.y())])


class MarkerView(QGraphicsView):
    moved = Signal(list)           # [(placement, dx, dy)]
    dragging = Signal()            # a piece is being moved (live length in the status bar)
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
        self.apply_theme()
        self.options = dict(DEFAULT_OPTIONS)
        self.last_result = None       # (length_mm, efficiency_pct) of the previous marker, for "last efficiency"
        self.efficiency = None
        self.bad: set[str] = set()
        self.items_by_uid: dict[str, PieceItem] = {}
        self.project = None
        self.marker = None
        self.model_tags: list[str] = []
        self.measure_mode = False
        self._m_start = self._m_end = self._m_hover = None   # scene points (mm)
        self._m_fixed = False
        self.measure_kind = "line"          # "line" (straight) or "curve" (along a piece contour)
        self._c_start = self._c_end = None   # (item uid, arc position, point) on the contour
        self._c_arc: list = []               # scene points of the measured arc
        self._c_len = None
        self._snap_pts: list[tuple[float, float]] = []
        self._measure_item = None
        self._pan = None

    def apply_theme(self):
        from .themes import colours
        self.theme = colours()
        self.setBackgroundBrush(QBrush(self.theme["canvas"]))
        if getattr(self, "marker", None) is not None:
            self.show_marker(self.project, self.marker, self.bad)
        self.viewport().update()

    def show_marker(self, project, marker, bad=None):
        from ..service import model_tags
        self.model_tags = model_tags(project) if project is not None else []
        self.project, self.marker = project, marker
        self.bad = set(bad or [])
        sc = self.scene()
        sc.clear()
        self._measure_item = None
        self._m_start = self._m_end = None
        self._m_fixed = False
        self.items_by_uid = {}
        if marker is None:
            return
        L = max(marker.length, 100.0)
        W = marker.fabric.width
        bg = QColor(self.theme["fabric"])
        bg.setAlpha(int(255 * max(self.options["bg_opacity"], 35) / 100.0))
        sc.addRect(QRectF(0, 0, L, W), QPen(self.theme["fabric_line"], 0), QBrush(bg))
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
        self._aux_items = []
        self._draw_aux()
        # snap targets for the measure tool: piece contour vertices and fabric corners
        snaps = [(0.0, 0.0), (L, 0.0), (0.0, W), (L, W)]
        for it in self.items_by_uid.values():
            g = it.piece.sizes[it.placement.size]
            snaps.extend(placement_points(g.cut, it.placement))
        self._snap_pts = snaps
        sc.setSceneRect(QRectF(-200, -200, max(L, (self.last_result or (0,))[0]) + 400, W + 400))

    def _draw_aux(self):
        sc = self.scene()
        for it in getattr(self, "_aux_items", []):
            if it.scene():
                sc.removeItem(it)
        self._aux_items = []
        if self.marker is None:
            return
        W = self.marker.fabric.width
        o = self.options

        def vline(x, pen, label):
            ln = sc.addLine(x, -30, x, W + 30, pen)
            t = QGraphicsSimpleTextItem(label)
            t.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            t.setBrush(QBrush(pen.color()))
            t.setFont(QFont("Segoe UI", 8))
            t.setPos(x, W + 60)
            sc.addItem(t)
            self._aux_items += [ln, t]
        if o["efficiency_mark"]:
            eff = self.efficiency
            vline(self.marker.length, QPen(QColor(230, 30, 30), 0),
                  f"L {self.marker.length / 1000:.2f} m" + (f"  E {eff:.1f} %" if eff is not None else ""))
        if o["last_efficiency"] and self.last_result:
            ll, le = self.last_result
            pen = QPen(QColor(255, 255, 255) if o["white_marking"] else QColor(0, 0, 0), 0, Qt.DashLine)
            vline(ll, pen, f"{ll / 1000:.2f} m  {le:.1f} %")

    def set_options(self, **kw):
        old = self.view_angle()
        self.options.update(kw)
        if self.marker is not None:
            self.show_marker(self.project, self.marker, self.bad)
            if self.view_angle() != old:
                self.zoom_fit()

    def refresh(self, bad=None):
        if bad is not None:
            self.bad = set(bad)
        for it in self.items_by_uid.values():
            it.setFlag(QGraphicsItem.ItemIsMovable, not it.placement.pinned)
            it.rebuild()
        self._draw_aux()

    def view_angle(self) -> int:
        """Screen-only rotation chosen in the display options (90 / 180 / 270); the marker is not changed."""
        return (90 if self.options.get("view_rot90") else 0) + (180 if self.options.get("view_rot180") else 0)

    def base_transform(self) -> QTransform:
        return QTransform(1, 0, 0, -1, 0, 0) * QTransform().rotate(self.view_angle())   # Y up, then rotate

    def zoom_fit(self):
        if self.marker:
            self.setTransform(self.base_transform())
            self.fitInView(QRectF(-50, -50, max(self.marker.length, 100) + 100, self.marker.fabric.width + 100),
                           Qt.KeepAspectRatio)
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
        if self.measure_mode and ev.button() == Qt.RightButton:
            self.clear_measure()
            return
        if self.measure_mode and self.measure_kind == "curve" and ev.button() == Qt.LeftButton:
            hit = self._on_contour(self.mapToScene(ev.position().toPoint()))
            if hit is None:
                return
            if self._c_start is None or self._c_end is not None or hit[0] != self._c_start[0]:
                self._c_start, self._c_end, self._c_arc, self._c_len = hit, None, [], None
            else:
                self._c_end = hit
                self._update_arc(hit, ev.modifiers() & Qt.ShiftModifier)
                self.measured.emit(self._c_len or 0.0)
            self.viewport().update()
            return
        if self.measure_mode and ev.button() == Qt.LeftButton:
            p = self._snap(self.mapToScene(ev.position().toPoint()))
            if self._m_start is None or self._m_fixed:
                self._m_start, self._m_end, self._m_fixed = p, p, False
            else:
                self._m_end, self._m_fixed = p, True
                self.measured.emit(math.hypot(p.x() - self._m_start.x(), p.y() - self._m_start.y()))
            self.viewport().update()
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
        if self.measure_mode and self.measure_kind == "curve":
            hit = self._on_contour(p)
            self._m_hover = QPointF(*hit[2]) if hit else None
            if self._c_start is not None and self._c_end is None:
                if hit and hit[0] == self._c_start[0]:
                    self._update_arc(hit, ev.modifiers() & Qt.ShiftModifier)
                else:
                    self._c_arc, self._c_len = [], None
            self.viewport().update()
            return
        if self.measure_mode:
            q = self._snap(p)
            self._m_hover = q
            if self._m_start is not None and not self._m_fixed:
                self._m_end = q
            self.viewport().update()
            return
        super().mouseMoveEvent(ev)

    # -- measure tool ------------------------------------------------------------------------
    SNAP_PX = 10

    def set_measure_mode(self, on: bool, kind: str = "line"):
        self.measure_mode = on
        self.measure_kind = kind
        self.setDragMode(QGraphicsView.NoDrag if on else QGraphicsView.RubberBandDrag)
        self.viewport().setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        if not on:
            self.clear_measure()

    def clear_measure(self):
        self._c_start = self._c_end = None
        self._c_arc, self._c_len = [], None
        self._m_start = self._m_end = None
        self._m_fixed = False
        self.viewport().update()

    def _snap(self, p: QPointF):
        """Nearest piece vertex / fabric corner within SNAP_PX pixels, else the point itself."""
        scale = abs(self.transform().m11()) or 1.0
        r = self.SNAP_PX / scale
        best, bd = None, r
        for x, y in self._snap_pts:
            d = abs(x - p.x()) + abs(y - p.y())
            if d < bd * 1.5 and math.hypot(x - p.x(), y - p.y()) < bd:
                best, bd = (x, y), math.hypot(x - p.x(), y - p.y())
        q = QPointF(*best) if best else p
        q.snapped = best is not None        # type: ignore[attr-defined]
        return q

    # -- curve measuring ----------------------------------------------------------------------
    def _contour(self, uid):
        it = self.items_by_uid.get(uid)
        if it is None:
            return None
        return placement_points(it.piece.sizes[it.placement.size].cut, it.placement)

    def _on_contour(self, p: QPointF):
        """Nearest point on a piece contour within SNAP_PX: (uid, arc position from vertex 0, (x, y))."""
        scale = math.hypot(self.transform().m11(), self.transform().m12()) or 1.0
        tol = 2 * self.SNAP_PX / scale
        best = None
        px, py = p.x(), p.y()
        for uid, it in self.items_by_uid.items():
            r = it.mapToScene(it.path().boundingRect()).boundingRect()
            if not r.adjusted(-tol, -tol, tol, tol).contains(p):
                continue
            pts = self._contour(uid)
            acc = 0.0
            n = len(pts)
            for i in range(n):
                (ax, ay), (bx, by) = pts[i], pts[(i + 1) % n]
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                qx, qy = ax + t * dx, ay + t * dy
                d = math.hypot(px - qx, py - qy)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, uid, acc + t * math.sqrt(L2), (qx, qy))
                acc += math.sqrt(L2)
        return None if best is None else best[1:]

    def _update_arc(self, end, other_way=False):
        """Arc along the contour between the start and ``end``: the shorter one (Shift: the other one)."""
        uid, s1, p1 = self._c_start
        _, s2, p2 = end
        pts = self._contour(uid)
        n = len(pts)
        seg = [math.dist(pts[i], pts[(i + 1) % n]) for i in range(n)]
        per = sum(seg)
        fwd = (s2 - s1) % per
        forward = fwd <= per - fwd
        if other_way:
            forward = not forward
        a, b = (s1, s2) if forward else (s2, s1)          # walk forward from a to b
        length = (b - a) % per
        cum = [0.0]
        for L in seg[:-1]:
            cum.append(cum[-1] + L)               # arc position of every vertex
        arc = [p1 if forward else p2]
        for i in sorted(range(n), key=lambda i: (cum[i] - a) % per):
            if 1e-9 < (cum[i] - a) % per < length - 1e-9:
                arc.append(pts[i])
        arc.append(p2 if forward else p1)
        self._c_arc, self._c_len = arc, length

    def keyPressEvent(self, ev):
        if self.measure_mode and ev.key() == Qt.Key_Escape:
            self.clear_measure()
            return
        super().keyPressEvent(ev)

    def _draw_measure(self, painter: QPainter):
        accent = QColor(255, 0, 200)
        if self.measure_kind == "curve":
            if self._m_hover is not None:
                h = self.mapFromScene(self._m_hover)
                painter.setPen(QPen(accent, 1.5))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(h), 5, 5)
            if self._c_start is not None:
                painter.setBrush(accent)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(self.mapFromScene(QPointF(*self._c_start[2]))), 4, 4)
            if len(self._c_arc) >= 2:
                painter.setPen(QPen(accent, 3, Qt.SolidLine if self._c_end is not None else Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                pts = [QPointF(self.mapFromScene(QPointF(x, y))) for x, y in self._c_arc]
                painter.drawPolyline(QPolygonF(pts))
                painter.setBrush(accent)
                painter.drawEllipse(pts[-1], 4, 4)
                mid = pts[len(pts) // 2]
                self._label(painter, f"{self._c_len:.1f} mm", mid.x() + 12, mid.y() - 30)
            return
        if self._m_hover is not None and getattr(self._m_hover, "snapped", False):
            h = self.mapFromScene(self._m_hover)
            painter.setPen(QPen(accent, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(h.x() - 5, h.y() - 5, 10, 10))
        if self._m_start is None or self._m_end is None:
            return
        a, b = self.mapFromScene(self._m_start), self.mapFromScene(self._m_end)
        dx, dy = self._m_end.x() - self._m_start.x(), self._m_end.y() - self._m_start.y()
        d = math.hypot(dx, dy)
        painter.setPen(QPen(accent, 2, Qt.SolidLine if self._m_fixed else Qt.DashLine))
        painter.drawLine(a, b)
        painter.setBrush(accent)
        for pt in (a, b):
            painter.drawEllipse(QPointF(pt), 3.5, 3.5)
        txt = f"{d:.1f} mm"                     # only the distance between the two points
        self._label(painter, txt, (a.x() + b.x()) / 2 + 12, (a.y() + b.y()) / 2 - 30)

    def _label(self, painter, txt, x, y):
        f = QFont("Segoe UI", 10)
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        w, h = fm.horizontalAdvance(txt) + 16, fm.height() + 8
        mx, my = x, y
        mx = max(44, min(mx, self.viewport().width() - w - 4))
        my = max(22, min(my, self.viewport().height() - h - 4))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 225))
        painter.drawRoundedRect(QRectF(mx, my, w, h), 5, 5)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QRectF(mx, my, w, h), Qt.AlignCenter, txt)

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
        rb = QColor(self.theme["ruler"])
        rb.setAlpha(235)
        painter.fillRect(0, 0, vw, 18, rb)
        painter.fillRect(0, 0, 40, vh, rb)
        painter.setPen(self.theme["ruler_text"])
        painter.setFont(QFont("Segoe UI", 7))
        t = self.transform()
        scale = math.hypot(t.m11(), t.m12()) or 1.0
        step = 10.0
        for st in (10, 20, 50, 100, 200, 500, 1000, 2000):
            if st * scale >= 60:
                step = st
                break

        def ticks(p0, p1):
            """Scene axis that varies along the screen segment p0-p1 (works for any quarter-turn view)."""
            a0, a1 = self.mapToScene(*p0), self.mapToScene(*p1)
            ax = 0 if abs(a1.x() - a0.x()) >= abs(a1.y() - a0.y()) else 1
            lo, hi = sorted(((a0.x(), a1.x()) if ax == 0 else (a0.y(), a1.y())))
            v = math.floor(lo / step) * step
            while v <= hi:
                q = QPointF(v, a0.y()) if ax == 0 else QPointF(a0.x(), v)
                yield v, self.mapFromScene(q)
                v += step
        for v, q in ticks((0, 0), (vw, 0)):
            painter.drawLine(q.x(), 12, q.x(), 18)
            painter.drawText(q.x() + 2, 11, f"{v:g}")
        for v, q in ticks((0, 0), (0, vh)):
            painter.drawLine(34, q.y(), 40, q.y())
            painter.drawText(2, q.y() - 2, f"{v:g}")
        painter.drawText(44, 11, "mm")
        if self.measure_mode:
            painter.setRenderHint(QPainter.Antialiasing)
            self._draw_measure(painter)
        painter.restore()


_ = QPolygonF
