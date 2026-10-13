"""Customize the toolbar: order of the icons (drag or Up / Down), show / hide, separators."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from .i18n import tr

SEP = "|"


class ToolbarDialog(QDialog):
    def __init__(self, parent, entries, actions, hidden, default_entries):
        """entries: keys in order ("|" = separator); actions: key -> QAction; hidden: set of keys."""
        super().__init__(parent)
        self.setWindowTitle(tr("tb_customize"))
        self.resize(420, 560)
        self.actions, self.default_entries = actions, default_entries
        v = QVBoxLayout(self)
        hint = QLabel(tr("tb_customize_hint"))
        hint.setWordWrap(True)
        v.addWidget(hint)
        h = QHBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        h.addWidget(self.list, 1)
        side = QVBoxLayout()
        for key, fn in (("tb_up", lambda: self._move(-1)), ("tb_down", lambda: self._move(1)),
                        ("tb_add_sep", self._add_sep), ("tb_remove_sep", self._remove_sep),
                        ("tb_reset", lambda: self._fill(self.default_entries, set()))):
            b = QPushButton(tr(key))
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch(1)
        h.addLayout(side)
        v.addLayout(h, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._fill(entries, hidden)

    def _item(self, key, shown=True):
        if key == SEP:
            it = QListWidgetItem("──────────  " + tr("tb_separator"))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        else:
            a = self.actions[key]
            it = QListWidgetItem(a.icon(), a.iconText().replace("&", ""))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if shown else Qt.Unchecked)
        it.setData(Qt.UserRole, key)
        return it

    def _fill(self, entries, hidden):
        self.list.clear()
        for k in entries:
            if k == SEP or k in self.actions:
                self.list.addItem(self._item(k, k not in hidden))

    def _move(self, d):
        r = self.list.currentRow()
        if r < 0 or not 0 <= r + d < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + d, it)
        self.list.setCurrentRow(r + d)

    def _add_sep(self):
        r = self.list.currentRow()
        self.list.insertItem(r + 1 if r >= 0 else self.list.count(), self._item(SEP))

    def _remove_sep(self):
        it = self.list.currentItem()
        if it is not None and it.data(Qt.UserRole) == SEP:
            self.list.takeItem(self.list.row(it))

    def result_order(self):
        """(entries, hidden)"""
        keys, hidden = [], set()
        for i in range(self.list.count()):
            it = self.list.item(i)
            k = it.data(Qt.UserRole)
            keys.append(k)
            if k != SEP and it.checkState() != Qt.Checked:
                hidden.add(k)
        return keys, hidden
