"""Plot (PLT) settings: choose what is printed; device format settings are kept under "Advanced"."""
from __future__ import annotations

import json
from dataclasses import asdict

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout)

from ..exporters.plt import PRESETS, PlotterConfig
from .i18n import tr

# (layer, i18n key, kind) — kind "path": pen per layer; "text": member of text_layers (drawn with the TEXT pen)
PRINT_ITEMS = (("CUT", "pi_cut", "path"), ("NOTCH", "pi_notch", "path"), ("SEAM", "pi_seam", "path"),
               ("INTERNAL", "pi_internal", "path"), ("GRAIN", "pi_grain", "path"), ("TEXT", "pi_text", "text"),
               ("PIECE_NAME", "pi_piece_name", "text"), ("MEASURE", "pi_measure", "text"),
               ("BORDER", "pi_border", "path"))
SETTINGS_KEY = "plt_config"


def default_config(settings) -> PlotterConfig:
    """Last saved settings, else the GRAFIS-compatible Algotex preset (the format the plotter accepted)."""
    raw = settings.value(SETTINGS_KEY, "")
    if raw:
        try:
            return PlotterConfig.from_dict(json.loads(raw))
        except Exception:
            pass
    return PRESETS["algotex_grafis"]()


def enabled_items(cfg: PlotterConfig) -> dict[str, bool]:
    out = {}
    for layer, _k, kind in PRINT_ITEMS:
        if kind == "path":
            out[layer] = cfg.pens.get(layer, 0) > 0
        else:
            out[layer] = layer in cfg.text_layers and cfg.pens.get("TEXT", 0) > 0 and \
                (cfg.text_mode != "label" or cfg.include_text) and cfg.text_mode != "none"
    return out


def apply_items(cfg: PlotterConfig, on: dict[str, bool]) -> PlotterConfig:
    """Switch printed items on/off without touching the file format of the chosen preset."""
    generic = PlotterConfig().pens
    pens = dict(cfg.pens)
    for layer, _k, kind in PRINT_ITEMS:
        if kind != "path":
            continue
        if layer == "CUT" or on.get(layer):
            if pens.get(layer, 0) <= 0:
                pens[layer] = 1 if cfg.dialect == "grafis" else (generic.get(layer, 1) or 1)
        else:
            pens[layer] = 0
    texts = [layer for layer, _k, kind in PRINT_ITEMS if kind == "text" and on.get(layer)]
    cfg.text_layers = texts
    if texts:
        if pens.get("TEXT", 0) <= 0:
            pens["TEXT"] = 1 if cfg.dialect == "grafis" else (generic.get("TEXT", 3) or 1)
        if cfg.text_mode == "none":
            cfg.text_mode = "strokes"
        cfg.include_text = True
    else:
        pens["TEXT"] = 0
    cfg.pens = pens
    return cfg


class PlotSettingsDialog(QDialog):
    def __init__(self, parent, cfg: PlotterConfig):
        super().__init__(parent)
        self.setWindowTitle(tr("plotter_settings"))
        self.cfg = PlotterConfig(**asdict(cfg))
        lay = QVBoxLayout(self)
        top = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem(tr("plt_preset_algotex"), "algotex_grafis")
        self.preset.addItem(tr("plt_preset_generic"), "generic")
        self.preset.setCurrentIndex(0 if self.cfg.dialect == "grafis" else 1)
        top.addRow(tr("plt_preset"), self.preset)
        self.line = QComboBox()
        self.line.addItem(tr("plt_line_solid"), "solid")
        self.line.addItem(tr("plt_line_lt1"), "lt1")
        self.line.setCurrentIndex(1 if self.cfg.line_type == "lt1" else 0)
        top.addRow(tr("plt_line"), self.line)
        lay.addLayout(top)

        box = QGroupBox(tr("plt_what"))
        g = QGridLayout(box)
        self.checks = {}
        on = enabled_items(self.cfg)
        for i, (layer, key, _kind) in enumerate(PRINT_ITEMS):
            c = QCheckBox(tr(key))
            c.setChecked(on[layer] or layer == "CUT")
            if layer == "CUT":
                c.setEnabled(False)             # the cut line is always plotted
            g.addWidget(c, i // 2, i % 2)
            self.checks[layer] = c
        lay.addWidget(box)
        note = QLabel(tr("plt_note"))
        note.setWordWrap(True)
        lay.addWidget(note)

        self.adv = QGroupBox(tr("plt_advanced"))
        self.adv.setCheckable(True)
        self.adv.setChecked(False)
        f = QFormLayout(self.adv)
        self.dialect = QComboBox()
        self.dialect.addItems(["grafis", "hpgl"])
        self.tmode = QComboBox()
        self.tmode.addItems(["strokes", "label", "none"])
        self.merge = QCheckBox()
        self.upm = QDoubleSpinBox()
        self.upm.setRange(1, 1000)
        self.upm.setDecimals(3)
        self.swap, self.fx, self.fy = QCheckBox(), QCheckBox(), QCheckBox()
        self.text_h = QDoubleSpinBox()
        self.text_h.setRange(2, 100)
        f.addRow(tr("plt_dialect"), self.dialect)
        f.addRow(tr("plt_text_mode"), self.tmode)
        f.addRow(tr("plt_merge_notches"), self.merge)
        f.addRow("units / mm", self.upm)
        f.addRow("swap X/Y", self.swap)
        f.addRow("flip X", self.fx)
        f.addRow("flip Y", self.fy)
        self.pens = {}
        for layer in ("CUT", "NOTCH", "SEAM", "INTERNAL", "GRAIN", "TEXT", "BORDER"):
            s = QSpinBox()
            s.setRange(1, 8)
            self.pens[layer] = s
            f.addRow(f"pen {layer}", s)
        lay.addWidget(self.adv)
        self._load(self.cfg)
        self.preset.activated.connect(self._preset_chosen)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.RestoreDefaults).setText(tr("plt_reset"))
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self._preset_chosen(0))
        lay.addWidget(bb)

    def _load(self, c: PlotterConfig):
        self.dialect.setCurrentText(c.dialect)
        self.tmode.setCurrentText(c.text_mode)
        self.merge.setChecked(c.merge_notches)
        self.upm.setValue(c.units_per_mm)
        self.swap.setChecked(c.swap_xy)
        self.fx.setChecked(c.flip_x)
        self.fy.setChecked(c.flip_y)
        for k, s in self.pens.items():
            s.setValue(max(1, c.pens.get(k, 1)))

    def _preset_chosen(self, i):
        self.preset.setCurrentIndex(i)
        c = PRESETS[self.preset.itemData(i)]()
        self.cfg = c
        self._load(c)
        self.line.setCurrentIndex(1 if c.line_type == "lt1" else 0)
        on = enabled_items(c)
        for layer, ch in self.checks.items():
            ch.setChecked(on[layer] or layer == "CUT")

    def result_config(self) -> PlotterConfig:
        c = self.cfg
        c.line_type = self.line.currentData()
        if self.adv.isChecked():
            c.dialect, c.text_mode = self.dialect.currentText(), self.tmode.currentText()
            c.merge_notches = self.merge.isChecked()
            c.units_per_mm = self.upm.value()
            c.swap_xy, c.flip_x, c.flip_y = self.swap.isChecked(), self.fx.isChecked(), self.fy.isChecked()
            for k, s in self.pens.items():
                if c.pens.get(k, 0) > 0:
                    c.pens[k] = s.value()
        return apply_items(c, {k: ch.isChecked() for k, ch in self.checks.items()})
