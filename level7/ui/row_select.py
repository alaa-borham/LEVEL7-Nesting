"""Whole-row selection for tables with field boxes in their cells (pieces table).

Clicking any box of a row selects that row, and the boxes of selected rows are highlighted like the text cells
(QSS property rowSelected, see themes.py)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject


class RowSelect(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.t = table
        table.itemSelectionChanged.connect(self.refresh)

    def attach(self):
        """Call after the cell widgets were (re)created."""
        for r in range(self.t.rowCount()):
            for c in range(self.t.columnCount()):
                w = self.t.cellWidget(r, c)
                if w is not None:
                    w.setProperty("row", r)
                    w.installEventFilter(self)
                    for child in w.findChildren(QObject):      # the line edit inside a spin / combo box
                        if hasattr(child, "installEventFilter") and hasattr(child, "setProperty"):
                            child.setProperty("row", r)
                            child.installEventFilter(self)
        self.refresh()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            r = obj.property("row")
            if r is not None and self.t.currentRow() != r:
                self.t.selectRow(int(r))
        return False

    def refresh(self):
        rows = {i.row() for i in self.t.selectedIndexes()}
        for r in range(self.t.rowCount()):
            on = r in rows
            for c in range(self.t.columnCount()):
                w = self.t.cellWidget(r, c)
                if w is not None and bool(w.property("rowSelected")) != on:
                    w.setProperty("rowSelected", on)
                    w.style().unpolish(w)
                    w.style().polish(w)
