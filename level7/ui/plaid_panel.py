"""Plaid / stripe panel (toolbar "Plaid"): fabric repeat and the match point of each piece."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QVBoxLayout, QWidget)

from .i18n import tr


def _spin(lo, hi, dec=1, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSuffix(suffix)
    s.setFixedWidth(110)
    return s


class PlaidPanel(QWidget):
    fabric_changed = Signal()          # repeat / offset edited
    rules_changed = Signal()           # a piece's match rule edited / removed
    pick_toggled = Signal(bool)        # "pick match point" mode on the marker

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.rx, self.ry = _spin(0, 2000), _spin(0, 2000)
        self.ox, self.oy = _spin(-2000, 2000), _spin(-2000, 2000)
        self.labels = []
        for key, w in (("plaid_rx", self.rx), ("plaid_ry", self.ry), ("plaid_ox", self.ox), ("plaid_oy", self.oy)):
            lab = QLabel()
            self.form.addRow(lab, w)
            self.labels.append((lab, w, key))
            w.valueChanged.connect(lambda *_: self.fabric_changed.emit())
        v.addLayout(self.form)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.table = QTableWidget(0, 6)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        b = QHBoxLayout()
        self.b_pick = QPushButton()
        self.b_pick.setCheckable(True)
        self.b_pick.toggled.connect(self.pick_toggled.emit)
        self.b_remove = QPushButton()
        self.b_remove.clicked.connect(self._remove)
        b.addWidget(self.b_pick)
        b.addWidget(self.b_remove)
        b.addStretch(1)
        v.addLayout(b)
        self.retranslate()

    def retranslate(self):
        for lab, w, key in self.labels:
            lab.setText(tr(key))
            lab.setToolTip(tr("ft_" + key))
            w.setToolTip(tr("ft_" + key))
        self.hint.setText(tr("plaid_hint"))
        self.table.setHorizontalHeaderLabels([tr(k) for k in ("col_name", "plaid_anchor", "plaid_mx", "plaid_my",
                                                              "plaid_dx", "plaid_dy")])
        self.b_pick.setText(tr("plaid_pick"))
        self.b_remove.setText(tr("plaid_remove"))

    # -- fabric values -------------------------------------------------------------------
    def values(self) -> dict:
        return {"repeat_x": self.rx.value(), "repeat_y": self.ry.value(),
                "repeat_offset_x": self.ox.value(), "repeat_offset_y": self.oy.value()}

    def set_values(self, f):
        for w, val in ((self.rx, f.repeat_x), (self.ry, f.repeat_y), (self.ox, f.repeat_offset_x),
                       (self.oy, f.repeat_offset_y)):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)

    # -- rules table -----------------------------------------------------------------------
    def set_project(self, project):
        self.project = project
        self.fill()

    def fill(self):
        t = self.table
        t.setRowCount(0)
        if self.project is None:
            return
        for pc in self.project.pieces:
            m = pc.match
            if not m:
                continue
            r = t.rowCount()
            t.insertRow(r)
            from PySide6.QtWidgets import QTableWidgetItem
            it = QTableWidgetItem(pc.name)
            it.setData(Qt.UserRole, pc.uid)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, 0, it)
            a = QTableWidgetItem(tr("plaid_notch" if m.get("kind") == "notch" else "plaid_corner",
                                    n=int(m.get("index", 0)) + 1))
            a.setFlags(a.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, 1, a)
            for c, k in ((2, "x"), (3, "y")):
                cb = QCheckBox()
                cb.setChecked(bool(m.get(k)))
                cb.toggled.connect(lambda on, p=pc, k=k: self._set(p, k, on))
                t.setCellWidget(r, c, cb)
            for c, k in ((4, "dx"), (5, "dy")):
                s = _spin(-2000, 2000)
                s.setFixedWidth(90)
                s.setValue(float(m.get(k, 0.0)))
                s.valueChanged.connect(lambda val, p=pc, k=k: self._set(p, k, val))
                t.setCellWidget(r, c, s)
        t.resizeColumnsToContents()

    def _set(self, piece, key, value):
        if piece.match is not None:
            piece.match[key] = value
            self.rules_changed.emit()

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()} or
                      ({self.table.currentRow()} if self.table.currentRow() >= 0 else set()))
        if not rows or self.project is None:
            return
        for r in rows:
            uid = self.table.item(r, 0).data(Qt.UserRole)
            self.project.piece(uid).match = None
        self.fill()
        self.rules_changed.emit()
