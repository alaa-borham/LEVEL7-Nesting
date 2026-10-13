"""Drop-down panel under a toolbar button (pieces table / size quantities)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
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
        # the title is a handle: drag the panel anywhere on the screen; it reopens where it was left
        self.title.setCursor(Qt.SizeAllCursor)
        self.title.installEventFilter(self)
        self._drag = None
        self.user_pos = None
        lay.addWidget(self.title)
        lay.addWidget(widget, 1)
        self.widget = widget
        self.resize(size)

    def eventFilter(self, obj, ev):
        if obj is self.title:
            t = ev.type()
            if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if t == QEvent.MouseMove and self._drag is not None:
                self.move(ev.globalPosition().toPoint() - self._drag)
                self.user_pos = self.pos()
                return True
            if t == QEvent.MouseButtonRelease and self._drag is not None:
                self._drag = None
                return True
            if t == QEvent.MouseButtonDblClick:          # double-click the title: back under its icon
                self.user_pos = None
                return True
        return super().eventFilter(obj, ev)

    def show_below(self, anchor):
        """Open under ``anchor`` (a toolbar button), aligned to its side and kept on screen - or where the user
        last dragged it."""
        from .i18n import tr
        self.title.setToolTip(tr("popup_move_tip"))
        self.show()                      # final size is known only once shown; position afterwards
        if self.user_pos is not None:
            scr = (QGuiApplication.screenAt(self.user_pos) or QGuiApplication.primaryScreen()).availableGeometry()
            x = max(scr.left(), min(self.user_pos.x(), scr.right() - 40))
            y = max(scr.top(), min(self.user_pos.y(), scr.bottom() - 40))
            self.move(x, y)
            self.raise_()
            self.activateWindow()
            return
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
