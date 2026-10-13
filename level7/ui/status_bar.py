"""Status bar whose messages never draw over the permanent figures (L / E / U/B / Wi, progress).

QStatusBar paints a temporary message across the whole bar; in a narrow (or right-to-left) window it ran over
the permanent widgets. Here the message is an ordinary label that gets the space left and is shortened with "…"
(full text in its tooltip)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy, QStatusBar


class ElidedLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def set_full_text(self, text: str):
        self._full = text or ""
        self.setToolTip(self._full)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, self.width() - 4)))


class StatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self.msg = ElidedLabel(self)
        self.addWidget(self.msg, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clearMessage)

    def showMessage(self, text: str, timeout: int = 0):     # noqa: N802 (Qt API)
        self.msg.set_full_text(text)
        self._timer.stop()
        if timeout > 0:
            self._timer.start(timeout)

    def clearMessage(self):                                   # noqa: N802
        self.msg.set_full_text("")

    def currentMessage(self) -> str:                          # noqa: N802
        return self.msg.full_text()
