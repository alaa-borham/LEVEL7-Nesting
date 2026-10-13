"""Status bar whose messages never draw over the permanent figures (L / E / U/B / Wi, progress).

QStatusBar paints a temporary message across the whole bar; in a narrow (or right-to-left) window it ran over
the permanent widgets. Here the message is an ordinary label that gets the space left and is shortened with "…"
(full text in its tooltip)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QStatusBar, QWidget


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


class StatChips(QWidget):
    """L / E / U/B / Wi, each value in its own box (always visible on the right of the status bar)."""
    KEYS = ("L", "E", "U/B", "Wi")

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.setLayoutDirection(Qt.LeftToRight)       # same order as GRAFIS in both languages
        self.chips = {}
        for k in self.KEYS:
            lab = QLabel()
            lab.setObjectName("statChip")
            lab.setAlignment(Qt.AlignCenter)
            lab.hide()
            lay.addWidget(lab)
            self.chips[k] = lab

    def set_values(self, values: dict):
        for k, lab in self.chips.items():
            v = values.get(k)
            lab.setText(f"{k}&nbsp;&nbsp;<b>{v}</b>" if v is not None else "")
            lab.setProperty("v", v)
            lab.setVisible(v is not None)

    def clear(self):
        self.set_values({})

    def text(self) -> str:
        return "   ".join(f"{k} = {lab.property('v')}" for k, lab in self.chips.items() if lab.isVisible())


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
