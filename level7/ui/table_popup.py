"""Drop-down panel under a toolbar button (pieces table / size quantities)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class TablePopup(QFrame):
    closed = Signal()

    def __init__(self, parent, widget, size: QSize):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_NoMouseReplay, True)     # clicking the icon again just closes the panel
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.title = QLabel()
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)
        lay.addWidget(widget, 1)
        self.widget = widget
        self.resize(size)

    def show_below(self, anchor):
        """Open under ``anchor`` (a toolbar button), aligned to its side and kept on screen."""
        self.show()                      # final size is known only once shown; position afterwards
        if anchor is None:
            pos = self.parentWidget().mapToGlobal(QPoint(40, 80))
        else:
            rtl = anchor.layoutDirection() == Qt.RightToLeft
            corner = anchor.rect().bottomRight() if rtl else anchor.rect().bottomLeft()
            pos = anchor.mapToGlobal(corner)
            if rtl:
                pos.setX(pos.x() - self.width())
        scr = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
        x = max(scr.left(), min(pos.x(), scr.right() - self.width()))
        y = max(scr.top(), min(pos.y() + 2, scr.bottom() - self.height()))
        self.move(x, y)
        self.raise_()
        self.activateWindow()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.closed.emit()
