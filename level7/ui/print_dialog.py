"""Print dialog: paper (A4 / A3), orientation, whole marker or selected pieces, one page or real size (1:1), then
preview, print or save as PDF."""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QRadioButton, QVBoxLayout)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog

from . import printing
from .i18n import tr


class PrintMarkerDialog(QDialog):
    def __init__(self, window, project, marker, selected, title, info):
        super().__init__(window)
        self.setWindowTitle(tr("pr_title"))
        self.project, self.marker, self.selected, self.title_, self.info = project, marker, selected, title, info
        self.settings = window.settings_store
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.paper = QComboBox()
        self.paper.addItems(["A4", "A3"])
        self.paper.setCurrentText(str(self.settings.value("print/paper", "A4")))
        form.addRow(tr("pr_paper"), self.paper)
        self.orient = QComboBox()
        for key in ("pr_auto", "pr_portrait", "pr_landscape"):
            self.orient.addItem(tr(key))
        form.addRow(tr("pr_orientation"), self.orient)
        v.addLayout(form)
        self.what = QButtonGroup(self)
        self.r_all = QRadioButton(tr("pr_whole"))
        self.r_sel = QRadioButton(tr("pr_selected", n=len(selected)))
        self.r_sel.setEnabled(bool(selected))
        (self.r_sel if selected else self.r_all).setChecked(True)
        for b in (self.r_all, self.r_sel):
            self.what.addButton(b)
            v.addWidget(b)
        self.how = QButtonGroup(self)
        self.r_fit = QRadioButton(tr("pr_fit"))
        self.r_real = QRadioButton(tr("pr_real"))
        self.r_fit.setChecked(True)
        for b in (self.r_fit, self.r_real):
            self.how.addButton(b)
            v.addWidget(b)
        self.names = QCheckBox(tr("pr_names"))
        self.names.setChecked(True)
        self.fill = QCheckBox(tr("pr_fill"))
        self.fill.setChecked(True)
        self.wm = QCheckBox(tr("pr_watermark"))
        from .. import watermark as W
        self.wm.setEnabled(W.active(W.settings(project)))
        self.wm.setChecked(self.wm.isEnabled())
        v.addWidget(self.names)
        v.addWidget(self.fill)
        v.addWidget(self.wm)
        self.pages = QLabel()
        v.addWidget(self.pages)
        bs = QHBoxLayout()
        for key, fn in (("pr_preview", self.preview), ("pr_print", self.print_), ("pr_pdf", self.pdf),
                        ("cancel", self.reject)):
            b = QPushButton(tr(key))
            b.clicked.connect(fn)
            bs.addWidget(b)
        v.addLayout(bs)
        for w in (self.paper, self.orient):
            w.currentIndexChanged.connect(self._update)
        for b in (self.r_all, self.r_sel, self.r_fit, self.r_real):
            b.toggled.connect(self._update)
        self._update()

    def job(self) -> printing.PrintJob:
        pls = self.selected if self.r_sel.isChecked() else self.marker.placements
        return printing.build_job(self.project, self.marker, pls, self.title_, self.info,
                                  paper=self.paper.currentText(),
                                  orientation=("auto", "portrait", "landscape")[self.orient.currentIndex()],
                                  real_size=self.r_real.isChecked(), names=self.names.isChecked(),
                                  fill=self.fill.isChecked(), watermark=self.wm.isChecked())

    def _printer(self, job, mode=QPrinter.HighResolution) -> QPrinter:
        pr = QPrinter(mode)
        printing.setup_printer(pr, job)
        return pr

    def _update(self, *_):
        """Page count for the options chosen - one printer object for this (each new one opens the driver)."""
        job = self.job()
        if getattr(self, "_count_printer", None) is None:
            self._count_printer = QPrinter(QPrinter.ScreenResolution)
        printing.setup_printer(self._count_printer, job)
        self.pages.setText(tr("pr_pages", n=printing.page_count(self._count_printer, job)))

    def _remember(self):
        self.settings.setValue("print/paper", self.paper.currentText())

    def preview(self):
        job = self.job()
        pr = self._printer(job)
        dlg = QPrintPreviewDialog(pr, self)
        dlg.setWindowTitle(tr("pr_preview"))
        dlg.paintRequested.connect(lambda printer: printing.paint(printer, job))
        dlg.resize(1100, 800)
        dlg.exec()

    def print_(self):
        job = self.job()
        pr = self._printer(job)
        dlg = QPrintDialog(pr, self)
        if dlg.exec() != QDialog.Accepted:
            return
        printing.setup_printer(pr, job)           # the printer chosen keeps A4 / A3 and the orientation
        printing.paint(pr, job)
        self._remember()
        self.accept()

    def pdf(self):
        job = self.job()
        start = os.path.join(str(self.settings.value("export_dir", "")), f"{self.title_}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, tr("pr_pdf"), start, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        pr = self._printer(job)
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setOutputFileName(path)
        if not printing.paint(pr, job):
            QMessageBox.warning(self, tr("pr_pdf"), tr("pr_failed"))
            return
        self._remember()
        self.accept()
