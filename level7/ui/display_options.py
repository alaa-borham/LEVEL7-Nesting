"""Marker display options dialog (mirrors GRAFIS' "Marker display options")."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QLabel, QRadioButton,
                               QSlider, QVBoxLayout, QComboBox)

from .i18n import tr


class DisplayOptionsDialog(QDialog):
    CHECKS_PIECES = (("symbols", "opt_symbols"), ("size_bundle", "opt_size_bundle"), ("buffer", "opt_buffer"),
                     ("marking", "opt_marking"), ("grain", "opt_grain"), ("internal", "opt_internal"),
                     ("piece_names", "opt_piece_names"), ("direction", "opt_direction"))
    CHECKS_AUX = (("efficiency_mark", "opt_eff_mark"), ("last_efficiency", "opt_last_eff"),
                  ("white_marking", "opt_white"))
    CHECKS_VIEW = (("view_rot180", "opt_view_rot180"), ("view_rot90", "opt_view_rot90"))

    def __init__(self, options: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("display_options"))
        self.opts = dict(options)
        grid = QGridLayout(self)
        g1 = QGroupBox(tr("opt_in_pieces"))
        l1 = QVBoxLayout(g1)
        self.boxes = {}
        for key, label in self.CHECKS_PIECES:
            cb = QCheckBox(tr(label))
            cb.setChecked(bool(self.opts.get(key)))
            l1.addWidget(cb)
            self.boxes[key] = cb
        g2 = QGroupBox(tr("opt_aux"))
        l2 = QVBoxLayout(g2)
        for key, label in self.CHECKS_AUX:
            cb = QCheckBox(tr(label))
            cb.setChecked(bool(self.opts.get(key)))
            l2.addWidget(cb)
            self.boxes[key] = cb
        gv = QGroupBox(tr("opt_view_rotation"))
        lv = QVBoxLayout(gv)
        for key, label in self.CHECKS_VIEW:
            cb = QCheckBox(tr(label))
            cb.setChecked(bool(self.opts.get(key)))
            lv.addWidget(cb)
            self.boxes[key] = cb
        g3 = QGroupBox(tr("opt_show_pieces"))
        l3 = QVBoxLayout(g3)
        self.fill = {}
        for key, label in (("outline", "opt_outline"), ("solid", "opt_solid"), ("solid_outline", "opt_solid_outline")):
            rb = QRadioButton(tr(label))
            rb.setChecked(self.opts.get("fill") == key)
            l3.addWidget(rb)
            self.fill[key] = rb
        l3.addWidget(QLabel(tr("opt_bg_opacity")))
        self.bg = QSlider(Qt.Horizontal)
        self.bg.setRange(0, 100)
        self.bg.setValue(int(self.opts.get("bg_opacity", 25)))
        l3.addWidget(self.bg)
        l3.addWidget(QLabel(tr("opt_transparency")))
        self.tp = QSlider(Qt.Horizontal)
        self.tp.setRange(0, 100)
        self.tp.setValue(int(self.opts.get("piece_transparency", 50)))
        l3.addWidget(self.tp)
        self.inv = QCheckBox(tr("opt_inverse"))
        self.inv.setChecked(bool(self.opts.get("inverse_inner")))
        l3.addWidget(self.inv)
        self.mm = QCheckBox(tr("opt_status_mm"))
        self.mm.setChecked(bool(self.opts.get("status_mm")))
        l3.addWidget(self.mm)
        l3.addWidget(QLabel(tr("color_by")))
        self.color = QComboBox()
        self._color_keys = ["bundle", "size", "piece"]
        self.color.addItems([tr("color_bundle"), tr("color_size"), tr("color_piece")])
        self.color.setCurrentIndex(self._color_keys.index(self.opts.get("color_by", "bundle")))
        l3.addWidget(self.color)
        grid.addWidget(g1, 0, 0)
        grid.addWidget(g2, 1, 0)
        grid.addWidget(gv, 2, 0)
        grid.addWidget(g3, 0, 1, 3, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        grid.addWidget(bb, 3, 0, 1, 2)

    def result_options(self) -> dict:
        o = dict(self.opts)
        for k, cb in self.boxes.items():
            o[k] = cb.isChecked()
        o["fill"] = next(k for k, rb in self.fill.items() if rb.isChecked())
        o["bg_opacity"] = self.bg.value()
        o["piece_transparency"] = self.tp.value()
        o["inverse_inner"] = self.inv.isChecked()
        o["status_mm"] = self.mm.isChecked()
        o["color_by"] = self._color_keys[self.color.currentIndex()]
        return o
