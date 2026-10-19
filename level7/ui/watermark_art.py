"""Drawing the watermark (logo image / SVG or a word) - the same code for the marker view and for printing."""
from __future__ import annotations

import base64
import hashlib

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QTransform

COLORS = {"dark": QColor(30, 30, 30), "light": QColor(255, 255, 255)}
TEXT_ORIGINAL = QColor(40, 40, 40)
RASTER_W = 1600                  # SVG drawn at this width (print quality for a logo up to ~200 mm)
SCREEN_W = 480                   # smaller copy for the screen (hundreds of pieces)
PRINT_W = 1000                   # printed logo: ~125 dpi on a 200 mm logo, small enough for any printer driver


def load_image(data: bytes) -> QImage:
    """QImage of a logo file (SVG, PNG, JPG, WebP ...); a null image if it cannot be read."""
    img = QImage()
    if data.lstrip()[:5].lower() in (b"<?xml", b"<svg ") or b"<svg" in data[:2048]:
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(data))
        if not r.isValid():
            return QImage()
        s = r.defaultSize()
        w = RASTER_W
        h = max(1, round(w * s.height() / max(1, s.width()))) if s.width() > 0 else w
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, w, h))
        p.end()
        return img
    img.loadFromData(data)
    return img


def _tint(img: QImage, col: QColor) -> QImage:
    out = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), col)
    p.end()
    return out


class Art:
    """What is drawn: an image (with its screen copy) or a text path; ``aspect`` = width / height."""

    def __init__(self, cfg: dict):
        self.kind = cfg.get("kind", "image")
        self.opacity = max(0.02, min(1.0, float(cfg.get("opacity", 35)) / 100.0))
        col = cfg.get("color", "original")
        self.image = self.screen = None
        self.path = None
        self.aspect = 0.0
        if self.kind == "image":
            try:
                data = base64.b64decode(cfg.get("image_b64") or "")
            except (ValueError, TypeError):
                data = b""
            img = load_image(data) if data else QImage()
            if img.isNull() or img.width() < 1 or img.height() < 1:
                return
            if col in COLORS:
                img = _tint(img, COLORS[col])
            self.image = img
            self.screen = img.scaledToWidth(min(SCREEN_W, img.width()), Qt.SmoothTransformation)
            self.aspect = img.width() / img.height()
        else:
            text = (cfg.get("text") or "").strip()
            if not text:
                return
            f = QFont("Segoe UI", 100)
            f.setBold(True)
            path = QPainterPath()
            path.addText(0, 0, f, text)
            br = path.boundingRect()
            if br.width() <= 0 or br.height() <= 0:
                return
            self.path = path.translated(-br.x(), -br.y())
            self.colour = COLORS.get(col, TEXT_ORIGINAL)
            self.aspect = br.width() / br.height()

    @property
    def ok(self) -> bool:
        return self.aspect > 0

    def _opaque(self, bg: QColor) -> QImage:
        """The logo already blended onto the piece colour, without transparency, at print size (~1000 px): a
        printer driver cannot blend, so Qt turned every transparent logo into a page-resolution bitmap - with dozens
        of pieces the Windows print host ran out of memory (splwow64 0x8007000e)."""
        key = bg.rgb()
        img = self._opaque_cache.get(key) if hasattr(self, "_opaque_cache") else None
        if img is None:
            src = self.image.scaledToWidth(min(PRINT_W, self.image.width()), Qt.SmoothTransformation)
            img = QImage(src.size(), QImage.Format_RGB32)
            img.fill(bg)
            q = QPainter(img)
            q.setOpacity(self.opacity)
            q.drawImage(0, 0, src)
            q.end()
            self._opaque_cache = getattr(self, "_opaque_cache", {})
            self._opaque_cache[key] = img
        return img

    def draw(self, p: QPainter, tl, tr, bl, screen: bool = False, background: QColor | None = None):
        """Draw into the parallelogram tl / tr / bl (painter coordinates). ``background``: printing - the colour
        under the logo (piece fill); drawn without any transparency (see _opaque)."""
        if not self.ok:
            return
        if self.path is not None:
            br = self.path.boundingRect()
            W, H = br.width(), br.height()
        elif background is not None:
            src = self._opaque(background)
            W, H = src.width(), src.height()
        else:
            src = self.screen if screen else self.image
            W, H = src.width(), src.height()
        t = QTransform((tr[0] - tl[0]) / W, (tr[1] - tl[1]) / W, (bl[0] - tl[0]) / H, (bl[1] - tl[1]) / H,
                       tl[0], tl[1])
        p.save()
        if background is None:
            p.setOpacity(p.opacity() * self.opacity)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.Antialiasing, background is None)   # (a printer driver cannot antialias either)
        p.setTransform(t, True)
        if self.path is not None:
            p.setPen(Qt.NoPen)
            if background is not None:           # the text colour mixed with the piece colour: no transparency
                a, c, g = self.opacity, self.colour, background
                p.setBrush(QColor(round(g.red() + (c.red() - g.red()) * a), round(g.green() + (c.green() - g.green()) * a),
                                  round(g.blue() + (c.blue() - g.blue()) * a)))
            else:
                p.setBrush(self.colour)
            p.drawPath(self.path)
        else:
            p.drawImage(QPointF(0, 0), src)
        p.restore()


_ART: dict = {}


def art_for(cfg: dict) -> Art:
    """The drawing of these settings (kept: the logo is decoded once)."""
    key = hashlib.sha1(repr(sorted((k, v) for k, v in cfg.items() if k != "excluded")).encode()).hexdigest()
    a = _ART.get(key)
    if a is None:
        if len(_ART) > 8:
            _ART.clear()
        a = _ART[key] = Art(cfg)
    return a
