"""Watermark settings: a logo or a word on all pieces at once (screen and printing only), where it goes, size,
transparency, colour, and the pieces left without it. Changes show on the marker at once; Cancel undoes them."""
from __future__ import annotations

import base64
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSlider, QSpinBox,
                               QVBoxLayout)

from .. import watermark as W
from .i18n import tr

LOGO_FILTER = "Logo (*.svg *.png *.jpg *.jpeg *.webp *.SVG *.PNG *.JPG *.JPEG *.WEBP);;All (*)"
MAX_LOGO_BYTES = 8 * 1024 * 1024


class WatermarkDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.project = window.project
        self.setWindowTitle(tr("wm_title"))
        self.old = dict(self.project.watermark or {})
        self.cfg = W.settings(self.project)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._redraw)
        v = QVBoxLayout(self)
        self.on = QCheckBox(tr("wm_enable"))
        self.on.setChecked(bool(self.cfg["enabled"]))
        v.addWidget(self.on)
        note = QLabel(tr("wm_note"))
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        v.addWidget(note)
        kind = QHBoxLayout()
        self.r_img = QRadioButton(tr("wm_logo"))
        self.r_txt = QRadioButton(tr("wm_text"))
        g = QButtonGroup(self)
        for b in (self.r_img, self.r_txt):
            g.addButton(b)
            kind.addWidget(b)
        (self.r_txt if self.cfg["kind"] == "text" else self.r_img).setChecked(True)
        v.addLayout(kind)
        form = QFormLayout()
        logo = QHBoxLayout()
        self.b_logo = QPushButton(tr("wm_choose"))
        self.b_logo.clicked.connect(self.choose_logo)
        self.logo_name = QLabel(self.cfg.get("image_name") or tr("wm_no_logo"))
        logo.addWidget(self.b_logo)
        logo.addWidget(self.logo_name, 1)
        form.addRow(tr("wm_logo_file"), logo)
        self.preview = QLabel()
        self.preview.setFixedHeight(70)
        self.preview.setAlignment(Qt.AlignCenter)
        form.addRow("", self.preview)
        self.text = QLineEdit(self.cfg.get("text") or "")
        form.addRow(tr("wm_word"), self.text)
        self.pos = QComboBox()
        for k in W.POSITIONS:
            self.pos.addItem(tr("wm_pos_" + k), k)
        self.pos.setCurrentIndex(max(0, self.pos.findData(self.cfg["position"])))
        form.addRow(tr("wm_position"), self.pos)
        self.align = QComboBox()
        for k in ("grain", "long"):
            self.align.addItem(tr("wm_align_" + k), k)
        self.align.setCurrentIndex(max(0, self.align.findData(self.cfg["align"])))
        form.addRow(tr("wm_align"), self.align)
        self.upright = QCheckBox(tr("wm_upright"))
        self.upright.setChecked(bool(self.cfg.get("upright", True)))
        form.addRow("", self.upright)
        self.size = QSpinBox()
        self.size.setRange(10, 100)
        self.size.setSuffix(" %")
        self.size.setValue(int(self.cfg["size_pct"]))
        form.addRow(tr("wm_size"), self.size)
        self.max_mm = QDoubleSpinBox()
        self.max_mm.setRange(20, 2000)
        self.max_mm.setDecimals(0)
        self.max_mm.setSuffix(" mm")
        self.max_mm.setValue(float(self.cfg["max_mm"]))
        form.addRow(tr("wm_max"), self.max_mm)
        op = QHBoxLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(int(self.cfg["opacity"]))
        self.op_label = QLabel()
        op.addWidget(self.opacity, 1)
        op.addWidget(self.op_label)
        form.addRow(tr("wm_opacity"), op)
        self.color = QComboBox()
        for k in ("original", "dark", "light"):
            self.color.addItem(tr("wm_color_" + k), k)
        self.color.setCurrentIndex(max(0, self.color.findData(self.cfg["color"])))
        form.addRow(tr("wm_color"), self.color)
        v.addLayout(form)
        v.addWidget(QLabel(tr("wm_pieces")))
        self.pieces = QListWidget()
        self.pieces.setMaximumHeight(170)
        excl = set(self.cfg.get("excluded") or ())
        for pc in sorted(self.project.pieces, key=lambda p: (p.model, p.number if p.number is not None else 10 ** 6,
                                                               p.name)):
            it = QListWidgetItem(f"{pc.name}" + (f"  ({pc.material})" if pc.material else ""))
            it.setData(Qt.UserRole, pc.uid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if pc.uid in excl else Qt.Checked)
            self.pieces.addItem(it)
        v.addWidget(self.pieces)
        allb = QHBoxLayout()
        for key, state in (("wm_all", Qt.Checked), ("wm_none", Qt.Unchecked)):
            b = QPushButton(tr(key))
            b.clicked.connect(lambda _=False, s=state: self._check_all(s))
            allb.addWidget(b)
        allb.addStretch(1)
        v.addLayout(allb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.on, self.r_img, self.r_txt, self.upright):
            w.toggled.connect(self.apply)
        self.text.textChanged.connect(self.apply)
        for w in (self.pos, self.align, self.color):
            w.currentIndexChanged.connect(self.apply)
        for w in (self.size, self.max_mm, self.opacity):
            w.valueChanged.connect(self.apply)
        self.pieces.itemChanged.connect(self.apply)
        self._show_logo()
        self.apply()

    def _check_all(self, state):
        self.pieces.blockSignals(True)
        for i in range(self.pieces.count()):
            self.pieces.item(i).setCheckState(state)
        self.pieces.blockSignals(False)
        self.apply()

    def _show_logo(self):
        data = base64.b64decode(self.cfg.get("image_b64") or "") if self.cfg.get("image_b64") else b""
        if not data:
            self.preview.clear()
            return
        from .watermark_art import load_image
        img = load_image(data)
        if img.isNull():
            self.preview.setText(tr("wm_bad_logo"))
            return
        self.preview.setPixmap(QPixmap.fromImage(img).scaledToHeight(64, Qt.SmoothTransformation))

    def choose_logo(self):
        st = self.window_.settings_store
        path, _ = QFileDialog.getOpenFileName(self, tr("wm_choose"), str(st.value("wm_dir", "")), LOGO_FILTER)
        if not path:
            return
        try:
            data = open(path, "rb").read()
        except OSError as e:
            QMessageBox.warning(self, tr("wm_title"), str(e))
            return
        if len(data) > MAX_LOGO_BYTES:
            QMessageBox.warning(self, tr("wm_title"), tr("wm_too_big"))
            return
        from .watermark_art import load_image
        if load_image(data).isNull():
            QMessageBox.warning(self, tr("wm_title"), tr("wm_bad_logo"))
            return
        st.setValue("wm_dir", os.path.dirname(path))
        self.cfg["image_b64"] = base64.b64encode(data).decode("ascii")
        self.cfg["image_name"] = os.path.basename(path)
        self.logo_name.setText(self.cfg["image_name"])
        self.r_img.setChecked(True)
        self.on.setChecked(True)
        self._show_logo()
        self.apply()

    def settings(self) -> dict:
        c = dict(self.cfg)
        c.update(enabled=self.on.isChecked(), kind="text" if self.r_txt.isChecked() else "image",
                 text=self.text.text(), position=self.pos.currentData(), align=self.align.currentData(),
                 upright=self.upright.isChecked(), size_pct=self.size.value(), max_mm=self.max_mm.value(),
                 opacity=self.opacity.value(), color=self.color.currentData(),
                 excluded=[self.pieces.item(i).data(Qt.UserRole) for i in range(self.pieces.count())
                           if self.pieces.item(i).checkState() != Qt.Checked])
        return c

    def apply(self, *_):
        """Live preview on the marker (redrawn once the changes pause - hundreds of pieces)."""
        self.op_label.setText(f"{self.opacity.value()} %")
        img = self.r_img.isChecked()
        self.b_logo.setEnabled(img)
        self.text.setEnabled(not img)
        self.project.watermark = self.settings()
        self._timer.start()

    def _redraw(self):
        self.window_.view.refresh_watermark()

    def accept(self):
        self._timer.stop()
        self.project.watermark = self.settings()
        self._redraw()
        super().accept()

    def reject(self):
        self._timer.stop()
        self.project.watermark = self.old
        self.window_.view.refresh_watermark()
        super().reject()
