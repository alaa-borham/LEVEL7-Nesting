"""The mouse wheel never changes a value by accident.

Scrolling a table with spin boxes / combo boxes in its cells changed the value under the pointer (e.g. a grain
angle 90 -> 88). Inside item views the wheel now always scrolls the view; elsewhere it changes a field only
after the user clicked into it (it has the keyboard focus)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox

_GUARD = None


class _WheelGuard(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Wheel or not isinstance(obj, (QAbstractSpinBox, QComboBox)):
            return False
        view = _ancestor(obj, QAbstractItemView)
        if view is None and obj.hasFocus():
            return False                       # a focused field outside a table: the wheel changes it
        area = view or _ancestor(obj, QAbstractScrollArea)
        if area is not None:                   # scroll the table / panel instead
            QApplication.sendEvent(area.viewport(), ev)
        return True


def _ancestor(w, cls):
    p = w.parentWidget()
    while p is not None:
        if isinstance(p, cls):
            return p
        p = p.parentWidget()
    return None


def install():
    global _GUARD
    app = QApplication.instance()
    if app is None or _GUARD is not None:
        return
    _GUARD = _WheelGuard(app)
    app.installEventFilter(_GUARD)


_ = Qt
