"""Batch marker orders window: load a list, check it, nest / save / export every marker in sequence."""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import batch
from .i18n import tr

COLS = ("bt_marker", "bt_files", "bt_sizes", "bt_width", "bt_formats", "bt_length", "bt_eff", "bt_status")


class BatchWorker(QThread):
    order_changed = Signal(int)
    finished_all = Signal(str)

    def __init__(self, orders, outdir, plt_cfg, iso_cfg, default_time, default_attempts=1):
        super().__init__()
        self.orders, self.outdir = orders, outdir
        self.plt_cfg, self.iso_cfg, self.default_time = plt_cfg, iso_cfg, default_time
        self.default_attempts = default_attempts
        self.stop_event = threading.Event()

    def run(self):
        from ..nesting.slots import NEST_SLOTS
        s = batch.run_batch(self.orders, self.outdir, self.plt_cfg, self.iso_cfg, self.default_time,
                            on_order=lambda k, o: self.order_changed.emit(k), stop_event=self.stop_event,
                            slot=NEST_SLOTS, default_attempts=self.default_attempts)
        self.finished_all.emit(s)


class BatchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.setWindowTitle(tr("batch_title"))
        self.resize(1000, 520)
        self.orders: list[batch.MarkerOrder] = []
        self.list_path = ""
        self.outdir = ""
        self.worker = None
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.b_load = QPushButton(tr("batch_load"))
        self.b_tpl = QPushButton(tr("batch_template"))
        self.b_out = QPushButton(tr("batch_outdir"))
        self.time = QSpinBox()
        self.time.setRange(5, 3600)
        self.time.setValue(int(window.f_time.value()))
        self.time.setSuffix(" s")
        self.time.setToolTip(tr("batch_time_tip"))
        for b in (self.b_load, self.b_tpl, self.b_out):
            top.addWidget(b)
        top.addWidget(QLabel(tr("batch_time")))
        top.addWidget(self.time)
        self.attempts = QSpinBox()            # best result: attempts per marker, shortest kept
        self.attempts.setRange(1, 10)
        self.attempts.setValue(int(window.f_best.value()))
        self.attempts.setToolTip(tr("ft_best_of"))
        top.addWidget(QLabel(tr("best_of")))
        top.addWidget(self.attempts)
        top.addStretch(1)
        v.addLayout(top)
        self.info = QLabel(tr("batch_hint"))
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in COLS])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        v.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        self.b_start = QPushButton(tr("batch_start"))
        self.b_stop = QPushButton(tr("batch_stop"))
        self.b_open = QPushButton(tr("batch_open_markers"))
        self.b_folder = QPushButton(tr("batch_open_folder"))
        self.b_stop.setEnabled(False)
        self.b_open.setEnabled(False)
        self.b_folder.setEnabled(False)
        self.b_close = QPushButton(tr("batch_close"))
        for b in (self.b_start, self.b_stop, self.b_open, self.b_folder):
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(self.b_close)
        self.b_close.clicked.connect(self.close)
        v.addLayout(bottom)
        self.b_load.clicked.connect(self.load)
        self.b_tpl.clicked.connect(self.template)
        self.b_out.clicked.connect(self.choose_out)
        self.b_start.clicked.connect(self.start)
        self.b_stop.clicked.connect(self.stop)
        self.b_open.clicked.connect(self.open_markers)
        self.b_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.outdir)))
        self._update_buttons()

    # -- list ------------------------------------------------------------------------------
    def load(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("batch_load"), self.w.settings_store.value("last_dir", ""),
                                                  "Excel / CSV (*.xlsx *.xlsm *.csv *.txt)")
        if not path:
            return
        try:
            self.orders = batch.parse_orders(path)
        except Exception as exc:
            QMessageBox.warning(self, tr("batch_title"), f"{os.path.basename(path)}:\n{exc}")
            return
        self.list_path = path
        if not self.outdir:
            self.outdir = os.path.join(os.path.dirname(path), "LEVEL7_" + os.path.splitext(os.path.basename(path))[0])
        self.info.setText(tr("batch_loaded", n=len(self.orders), p=os.path.basename(path), o=self.outdir))
        self.fill()

    def template(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("batch_template"), "marker_orders.xlsx",
                                              "Excel (*.xlsx);;CSV (*.csv)")
        if path:
            batch.write_template(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def choose_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("batch_outdir"), self.outdir or "")
        if d:
            self.outdir = d
            if self.orders:
                self.info.setText(tr("batch_loaded", n=len(self.orders), p=os.path.basename(self.list_path), o=d))

    def fill(self):
        t = self.table
        t.setRowCount(len(self.orders))
        for r, o in enumerate(self.orders):
            files = sorted({os.path.basename(l.file) for l in o.lines})
            sizes = ", ".join(f"{l.size}×{l.qty}" for l in o.lines)
            vals = (o.name, " + ".join(files), sizes, f"{o.width:g}", " ".join(o.formats) or "—",
                    tr("bs_" + o.status) + (f" — {o.message}" if o.message else ""),
                    f"{o.length_mm:.0f}" if o.length_mm else "", f"{o.efficiency:.1f} %" if o.efficiency else "")
            vals = vals[:5] + vals[6:] + vals[5:6]          # status last: it may be long
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if c == 7:
                    it.setToolTip(val)
                    it.setForeground({"done": Qt.darkGreen, "failed": Qt.red, "running": Qt.blue}.get(o.status,
                                                                                                       Qt.gray))
                t.setItem(r, c, it)
        self._update_buttons()

    def _update_buttons(self):
        running = self.worker is not None and self.worker.isRunning()
        self.b_start.setEnabled(bool(self.orders) and not running)
        self.b_stop.setEnabled(running)
        for b in (self.b_load, self.b_tpl, self.b_out):
            b.setEnabled(not running)
        done = any(o.status == "done" for o in self.orders)
        self.b_open.setEnabled(done and not running)
        self.b_folder.setEnabled(bool(self.outdir) and os.path.isdir(self.outdir))

    # -- run -------------------------------------------------------------------------------
    def start(self):
        from ..exporters.iso import ISO_PRESETS
        for o in self.orders:
            o.status, o.message, o.length_mm, o.efficiency, o.outputs = "pending", "", None, None, []
        self.fill()
        self.worker = BatchWorker(self.orders, self.outdir, self.w.plt_config(), ISO_PRESETS["bullmer_grafis"](),
                                  float(self.time.value()), int(self.attempts.value()))
        self.worker.order_changed.connect(lambda k: self.fill())
        self.worker.finished_all.connect(self._finished)
        self.worker.start()
        self._update_buttons()

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()

    def _finished(self, summary):            # not 'done': that is QDialog.done(), called by the close button
        self.fill()
        ok = sum(1 for o in self.orders if o.status == "done")
        QMessageBox.information(self, tr("batch_title"), tr("batch_done", ok=ok, n=len(self.orders), s=summary))

    def open_markers(self):
        paths = [next((x for x in o.outputs if x.endswith(".l7n")), None) for o in self.orders if o.status == "done"]
        self.w.open_many([p for p in paths if p])

    def stop_and_wait(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            self.worker.wait()                  # never delete a running thread (that aborts the app)

    def closeEvent(self, ev):
        self.stop_and_wait()
        super().closeEvent(ev)

    def done(self, r):                          # Esc goes through reject() -> done(), not closeEvent
        self.stop_and_wait()
        super().done(r)
