"""Main window of the LEVEL7 Nesting desktop application."""
from __future__ import annotations

import copy
import math
import os
import threading
import traceback

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..geometry import bbox, placement_points
from ..model import FabricSettings, LayType, Marker, NestSettings, Placement, Project
from ..validation.checker import marker_stats, validate_marker
from .i18n import LANG, tr
from .marker_view import MarkerView


# ---------------------------------------------------------------------------------- undo
class PlacementStateCommand(QUndoCommand):
    def __init__(self, window, changes, text):
        super().__init__(text)
        self.window = window
        self.changes = changes  # [(placement, old_state, new_state)]

    @staticmethod
    def state(pl: Placement):
        return (pl.x, pl.y, pl.rotation, pl.mirrored, pl.pinned)

    @staticmethod
    def apply(pl, st):
        pl.x, pl.y, pl.rotation, pl.mirrored, pl.pinned = st

    def redo(self):
        for pl, _o, n in self.changes:
            self.apply(pl, n)
        self.window.after_edit()

    def undo(self):
        for pl, o, _n in self.changes:
            self.apply(pl, o)
        self.window.after_edit()


# -------------------------------------------------------------------------------- worker
class NestWorker(QThread):
    progress = Signal(dict)
    finished_ok = Signal(object, dict)
    failed = Signal(str)

    def __init__(self, project, fabric, settings, cut_order, pinned):
        super().__init__()
        self.project, self.fabric, self.settings = project, fabric, settings
        self.cut_order, self.pinned = cut_order, pinned
        self.stop_event = threading.Event()

    def run(self):
        from ..service import run_nesting
        try:
            marker, info = run_nesting(self.project, self.fabric, self.settings, self.cut_order, self.pinned,
                                       progress=lambda d: self.progress.emit(d), stop_event=self.stop_event)
            self.finished_ok.emit(marker, info)
        except Exception as e:
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings_store = QSettings("LEVEL7", "Nesting")
        LANG["current"] = self.settings_store.value("lang", "ar")
        self.project: Project | None = None
        self.project_path: str | None = None
        self.marker: Marker | None = None
        self.worker: NestWorker | None = None
        self.undo = QUndoStack(self)
        self.setAcceptDrops(True)
        self.resize(1400, 860)
        self.view = MarkerView(self)
        self.setCentralWidget(self.view)
        self.view.moved.connect(self.on_moved)
        self.view.cursor_mm.connect(lambda x, y: self.coord_label.setText(f"x {x:.1f}  y {y:.1f} mm"))
        self.view.measured.connect(lambda d: self.statusBar().showMessage(tr("distance", d=d)))
        self._build_docks()
        self._build_actions()
        self.coord_label = QLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.hide()
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.coord_label)
        self.retranslate()

    # -- construction --------------------------------------------------------------------
    def _build_docks(self):
        self.pieces_table = QTableWidget(0, 7)
        self.pieces_table.verticalHeader().hide()
        self.pieces_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sizes_table = QTableWidget(0, 2)
        self.sizes_table.verticalHeader().hide()
        left = QTabWidget()
        left.addTab(self.pieces_table, "")
        left.addTab(self.sizes_table, "")
        self.left_tabs = left
        self.dock_left = QDockWidget(self)
        self.dock_left.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_left)

        # fabric / nesting form
        w = QWidget()
        self.form = QFormLayout(w)
        self.f_width = self._dspin(100, 10000, 1500)
        self.f_ml = self._dspin(0, 500, 0)
        self.f_mr = self._dspin(0, 500, 0)
        self.f_ms = self._dspin(0, 2000, 0)
        self.f_me = self._dspin(0, 2000, 0)
        self.f_sp = self._dspin(0, 50, 0)
        self.f_lay = QComboBox()
        self.f_maxlen = self._dspin(0, 100000, 0)
        self.f_mode = QComboBox()
        self.f_time = QSpinBox()
        self.f_time.setRange(1, 7200)
        self.f_time.setValue(30)
        self.f_seed = QSpinBox()
        self.f_seed.setRange(0, 2 ** 31 - 1)
        self.f_seed.setValue(1)
        self.f_rot180 = QCheckBox()
        self.f_rot180.setChecked(True)
        self.f_rot90 = QCheckBox()
        self.f_tol = self._dspin(0.01, 2.0, 0.2, 2)
        self.f_material = QComboBox()
        self.form_rows = []
        for key, wid in (("width", self.f_width), ("margin_l", self.f_ml), ("margin_r", self.f_mr),
                         ("margin_s", self.f_ms), ("margin_e", self.f_me), ("spacing", self.f_sp), ("lay", self.f_lay),
                         ("max_len", self.f_maxlen), ("material", self.f_material), ("mode", self.f_mode),
                         ("time", self.f_time), ("seed", self.f_seed), ("rot180", self.f_rot180),
                         ("rot90", self.f_rot90), ("tolerance", self.f_tol)):
            lab = QLabel()
            self.form.addRow(lab, wid)
            self.form_rows.append((lab, key))
        self.f_mode.currentIndexChanged.connect(self._mode_changed)
        btns = QHBoxLayout()
        self.btn_run = QPushButton()
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_run.clicked.connect(self.run_nesting)
        self.btn_stop.clicked.connect(self.stop_nesting)
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_stop)
        self.form.addRow(btns)
        self.dock_fabric = QDockWidget(self)
        self.dock_fabric.setWidget(w)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_fabric)

        # results
        r = QWidget()
        rl = QVBoxLayout(r)
        self.markers_list = QListWidget()
        self.markers_list.currentRowChanged.connect(self.select_marker)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.unplaced_list = QListWidget()
        self.issues_list = QListWidget()
        self.res_labels = [QLabel(), QLabel(), QLabel()]
        rl.addWidget(self.res_labels[0])
        rl.addWidget(self.markers_list, 1)
        rl.addWidget(self.results_text, 3)
        rl.addWidget(self.res_labels[1])
        rl.addWidget(self.unplaced_list, 1)
        rl.addWidget(self.res_labels[2])
        rl.addWidget(self.issues_list, 1)
        self.dock_results = QDockWidget(self)
        self.dock_results.setWidget(r)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_results)

    @staticmethod
    def _dspin(lo, hi, val, dec=1):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setValue(val)
        return s

    def _act(self, key, slot, shortcut=None, checkable=False, checked=False):
        a = QAction(self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
        self.actions_tr.append((a, key))
        return a

    def _build_actions(self):
        self.actions_tr = []
        mb = self.menuBar()
        self.m_file, self.m_edit, self.m_view = mb.addMenu(""), mb.addMenu(""), mb.addMenu("")
        self.m_nest, self.m_export, self.m_help = mb.addMenu(""), mb.addMenu(""), mb.addMenu("")
        self.menus_tr = [(self.m_file, "file"), (self.m_edit, "edit"), (self.m_view, "view"),
                         (self.m_nest, "nesting"), (self.m_export, "export"), (self.m_help, "help")]
        self.m_file.addAction(self._act("open", self.open_dialog, "Ctrl+O"))
        self.m_file.addAction(self._act("save", self.save, "Ctrl+S"))
        self.m_file.addAction(self._act("save_as", self.save_as, "Ctrl+Shift+S"))
        self.m_file.addSeparator()
        self.m_file.addAction(self._act("language", self.toggle_language))
        undo = self.undo.createUndoAction(self, "")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.undo.createRedoAction(self, "")
        redo.setShortcut(QKeySequence.Redo)
        self.m_edit.addAction(undo)
        self.m_edit.addAction(redo)
        self.undo_actions = (undo, redo)
        self.m_edit.addAction(self._act("rotate180", self.rotate_selected, "R"))
        self.m_edit.addAction(self._act("pin", self.pin_selected, "P"))
        self.act_measure = self._act("measure", self.toggle_measure, "M", checkable=True)
        self.m_edit.addAction(self.act_measure)
        self.m_view.addAction(self._act("zoom_fit", self.view.zoom_fit, "F"))
        self.act_seam = self._act("show_seam", self.view_opts, checkable=True)
        self.act_int = self._act("show_internal", self.view_opts, checkable=True)
        self.act_grain = self._act("show_grain", self.view_opts, checkable=True, checked=True)
        self.act_labels = self._act("show_labels", self.view_opts, checkable=True, checked=True)
        self.act_color = self._act("color_by", self.view_opts, checkable=True, checked=True)
        for a in (self.act_seam, self.act_int, self.act_grain, self.act_labels, self.act_color):
            self.m_view.addAction(a)
        self.m_nest.addAction(self._act("run", self.run_nesting, "F5"))
        self.m_nest.addAction(self._act("stop", self.stop_nesting, "Esc"))
        self.m_export.addAction(self._act("export_plt", lambda: self.export("plt")))
        self.m_export.addAction(self._act("export_dxf", lambda: self.export("dxf")))
        self.m_export.addAction(self._act("export_iso", lambda: self.export("iso")))
        self.m_export.addSeparator()
        self.m_export.addAction(self._act("plotter_settings", self.plotter_settings))
        self.m_help.addAction(self._act("about", self.about))
        tb = self.addToolBar("main")
        tb.setObjectName("main")
        for a in self.actions_tr:
            if a[1] in ("open", "save", "run", "stop", "rotate180", "pin", "measure", "zoom_fit", "language"):
                tb.addAction(a[0])
        tb.addAction(undo)
        tb.addAction(redo)

    def retranslate(self):
        rtl = LANG["current"] == "ar"
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.setWindowTitle(f"{tr('app_title')} {__version__}" + (f" — {self.project.name}" if self.project else ""))
        for a, k in self.actions_tr:
            a.setText(tr(k))
        self.undo.setUndoLimit(500)
        self.undo_actions[0].setText(tr("undo"))
        self.undo_actions[1].setText(tr("redo"))
        self.act_color.setText(f"{tr('color_by')}: {tr('color_size')} / {tr('color_piece')}")
        for m, k in self.menus_tr:
            m.setTitle(tr(k))
        for lab, k in self.form_rows:
            lab.setText(tr(k))
        self.dock_left.setWindowTitle(tr("pieces"))
        self.dock_fabric.setWindowTitle(tr("fabric"))
        self.dock_results.setWindowTitle(tr("results"))
        self.left_tabs.setTabText(0, tr("pieces"))
        self.left_tabs.setTabText(1, tr("sizes"))
        self.pieces_table.setHorizontalHeaderLabels([tr(k) for k in ("col_use", "col_name", "col_mat", "col_sizes",
                                                                     "col_count", "col_mirror", "col_grain")])
        self.sizes_table.setHorizontalHeaderLabels([tr("col_size"), tr("col_qty")])
        self.res_labels[0].setText(tr("markers"))
        self.res_labels[1].setText(tr("unplaced"))
        self.res_labels[2].setText(tr("issues"))
        self.btn_run.setText(tr("run"))
        self.btn_stop.setText(tr("stop"))
        cur = self.f_lay.currentIndex()
        self.f_lay.clear()
        self.f_lay.addItems([tr("lay_open"), tr("lay_f2f"), tr("lay_folded")])
        self.f_lay.setCurrentIndex(max(cur, 0))
        cur = self.f_mode.currentIndex()
        self.f_mode.blockSignals(True)
        self.f_mode.clear()
        self.f_mode.addItems([tr("mode_fast"), tr("mode_balanced"), tr("mode_long")])
        self.f_mode.setCurrentIndex(cur if cur >= 0 else 1)
        self.f_mode.blockSignals(False)
        if not self.project:
            self.statusBar().showMessage(tr("ready"))
        self.update_results()

    def toggle_language(self):
        LANG["current"] = "en" if LANG["current"] == "ar" else "ar"
        self.settings_store.setValue("lang", LANG["current"])
        self.retranslate()

    def _mode_changed(self, i):
        self.f_time.setValue({0: 5, 1: 30, 2: 120}.get(i, 30))

    # -- file handling -------------------------------------------------------------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            if u.isLocalFile():
                self.open_path(u.toLocalFile())
                break

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("open"), self.settings_store.value("last_dir", ""),
                                           "Patterns / markers (*.mdl *.MDL *.scb *.SCB *.dxf *.DXF *.l7n);;All (*)")
        if p:
            self.open_path(p)

    def open_path(self, path):
        from ..service import open_any
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            proj, issues = open_any(path)
        except Exception as e:
            QMessageBox.critical(self, tr("open"), f"{os.path.basename(path)}:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.settings_store.setValue("last_dir", os.path.dirname(path))
        self.project = proj
        self.project_path = path if path.lower().endswith(".l7n") else None
        self.undo.clear()
        self.load_tables()
        if proj.markers:
            m = proj.markers[0]
            self.f_width.setValue(m.fabric.width)
        self.refresh_markers_list(select=0 if proj.markers else -1)
        msg = f"{os.path.basename(path)}: {len(proj.pieces)} pieces"
        if proj.sources and proj.sources[0].internal_model_name:
            msg += f" | internal model name: {proj.sources[0].internal_model_name}"
        if issues:
            msg += f" | {len(issues)} read issues"
            self.issues_list.addItems(issues[:200])
        self.statusBar().showMessage(msg)
        self.retranslate()

    def load_tables(self):
        p = self.project
        t = self.pieces_table
        t.setRowCount(0)
        co = p.cut_order
        for pc in sorted(p.pieces, key=lambda q: (not q.production, q.number or 0)):
            r = t.rowCount()
            t.insertRow(r)
            use = QTableWidgetItem()
            n, m = co.piece_counts.get(pc.uid, (0, 0))
            use.setCheckState(Qt.Checked if (n or m) else Qt.Unchecked)
            use.setData(Qt.UserRole, pc.uid)
            t.setItem(r, 0, use)
            t.setItem(r, 1, QTableWidgetItem(f"{pc.number or ''} {pc.name}"))
            t.setItem(r, 2, QTableWidgetItem(pc.material or ""))
            t.setItem(r, 3, QTableWidgetItem(str(len(pc.sizes))))
            for col, val in ((4, n or pc.default_count), (5, m if (n or m) else pc.default_mirrored)):
                s = QSpinBox()
                s.setRange(0, 20)
                s.setValue(val)
                t.setCellWidget(r, col, s)
            g = QDoubleSpinBox()
            g.setRange(-1, 179.99)
            g.setSpecialValueText(tr("grain_unknown"))
            g.setValue(pc.grain_angle if pc.grain_angle is not None else -1)
            t.setCellWidget(r, 6, g)
            for c in (1, 2, 3):
                t.item(r, c).setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        st = self.sizes_table
        st.setRowCount(0)
        for s in p.size_names:
            r = st.rowCount()
            st.insertRow(r)
            it = QTableWidgetItem(s)
            it.setFlags(Qt.ItemIsEnabled)
            st.setItem(r, 0, it)
            sp = QSpinBox()
            sp.setRange(0, 999)
            sp.setValue(co.size_quantities.get(s, 0))
            st.setCellWidget(r, 1, sp)
        mats = sorted({pc.material for pc in p.pieces if pc.material})
        self.f_material.clear()
        self.f_material.addItem("*")
        self.f_material.addItems(mats)
        if co.material in mats:
            self.f_material.setCurrentText(co.material)

    def read_tables(self):
        p = self.project
        co = p.cut_order
        for r in range(self.pieces_table.rowCount()):
            uid = self.pieces_table.item(r, 0).data(Qt.UserRole)
            pc = p.piece(uid)
            use = self.pieces_table.item(r, 0).checkState() == Qt.Checked
            n = self.pieces_table.cellWidget(r, 4).value()
            m = self.pieces_table.cellWidget(r, 5).value()
            co.piece_counts[uid] = (n, m) if use else (0, 0)
            g = self.pieces_table.cellWidget(r, 6).value()
            pc.grain_angle = None if g < 0 else g
        co.size_quantities = {self.sizes_table.item(r, 0).text(): self.sizes_table.cellWidget(r, 1).value()
                              for r in range(self.sizes_table.rowCount())}
        mat = self.f_material.currentText()
        co.material = None if mat in ("*", "") else mat

    def fabric_from_form(self) -> FabricSettings:
        lay = [LayType.OPEN, LayType.FACE_TO_FACE, LayType.FOLDED][max(0, self.f_lay.currentIndex())]
        return FabricSettings(width=self.f_width.value(), margin_left=self.f_ml.value(), margin_right=self.f_mr.value(),
                              margin_start=self.f_ms.value(), margin_end=self.f_me.value(), spacing=self.f_sp.value(),
                              lay_type=lay, max_length=self.f_maxlen.value() or None)

    def nest_settings_from_form(self) -> NestSettings:
        return NestSettings(mode=["fast", "balanced", "long"][max(0, self.f_mode.currentIndex())],
                            time_limit=float(self.f_time.value()), seed=self.f_seed.value(),
                            allow_rotation_180=self.f_rot180.isChecked(), allow_rotation_90=self.f_rot90.isChecked(),
                            curve_tolerance=self.f_tol.value())

    def save(self):
        if not self.project:
            return
        if not self.project_path:
            return self.save_as()
        from ..project_storage.store import save_project
        self.read_tables()
        save_project(self.project, self.project_path)
        self.statusBar().showMessage(tr("saved", p=self.project_path))

    def save_as(self):
        if not self.project:
            return
        p, _ = QFileDialog.getSaveFileName(self, tr("save_as"), os.path.join(
            self.settings_store.value("last_dir", ""), self.project.name + ".l7n"), "LEVEL7 project (*.l7n)")
        if p:
            if not p.lower().endswith(".l7n"):
                p += ".l7n"
            self.project_path = p
            self.save()

    # -- markers ---------------------------------------------------------------------------
    def refresh_markers_list(self, select=None):
        self.markers_list.blockSignals(True)
        self.markers_list.clear()
        for m in (self.project.markers if self.project else []):
            tag = tr("original") if m.origin == "original" else m.origin
            self.markers_list.addItem(QListWidgetItem(f"{m.name}  [{tag}]  L={m.length:.1f}"))
        self.markers_list.blockSignals(False)
        if select is not None and self.project and self.project.markers:
            idx = select if select >= 0 else len(self.project.markers) - 1
            self.markers_list.setCurrentRow(idx)
            self.select_marker(idx)
        elif not (self.project and self.project.markers):
            self.marker = None
            self.view.show_marker(self.project, None)

    def select_marker(self, i):
        if not self.project or i < 0 or i >= len(self.project.markers):
            return
        self.marker = self.project.markers[i]
        self.undo.clear()
        self.view.show_marker(self.project, self.marker)
        self.after_edit(fit=True)

    def validate_current(self):
        if not self.marker:
            return None
        from ..service import allowed_rotation_map
        allowed = None
        if self.marker.origin != "original":
            allowed = allowed_rotation_map(self.project, self.nest_settings_from_form())
            for pl in self.marker.placements:
                if pl.pinned:
                    allowed.setdefault((pl.piece_uid, pl.mirrored), []).append(pl.rotation)
        return validate_marker(self.project, self.marker, allowed_rotations=allowed)

    def after_edit(self, fit=False):
        if not self.marker:
            return
        v = self.validate_current()
        bad = {u for i in v.issues for u in i.placements}
        self.view.refresh(bad)
        self.marker.stats = marker_stats(self.project, self.marker)
        self.marker.length = self.marker.stats["length_mm"]
        self.issues_list.clear()
        self.issues_list.addItems([i.message for i in v.issues][:500] or [v.summary()])
        self.unplaced_list.clear()
        for pl in self.marker.placements:
            if not pl.placed:
                self.unplaced_list.addItem(f"{self.project.piece(pl.piece_uid).name} {pl.size}"
                                           f"{' (M)' if pl.mirrored else ''}: {pl.reason}")
        self.update_results(v)
        if fit:
            self.view.zoom_fit()

    def update_results(self, v=None):
        if not self.marker or not self.project:
            self.results_text.setPlainText("")
            return
        s = self.marker.stats or marker_stats(self.project, self.marker)
        lines = [f"{tr('width')}: {s['width_mm']:.1f}  ({s['usable_width_mm']:.1f} usable)",
                 f"Length: {s['length_mm']:.1f} mm", f"Placed / unplaced: {s['placed']} / {s['unplaced']}",
                 f"Pieces area: {s['pieces_area_m2']:.4f} m²",
                 f"Utilisation (total width): {s['efficiency_total_width_pct']:.2f} %",
                 f"Utilisation (usable width): {s['efficiency_usable_width_pct']:.2f} %",
                 f"Waste: {s['waste_pct']:.2f} %",
                 f"Consumption: {s['consumption_m']:.3f} m = {s['consumption_yd']:.3f} yd",
                 "By size: " + ", ".join(f"{k}: {n}" for k, n in sorted(s["by_size"].items()))]
        if self.marker.compute_time:
            lines.append(f"Compute time: {self.marker.compute_time:.1f} s, seed {self.marker.seed}")
        if v is not None:
            lines.append(f"{tr('issues')}: {tr('valid') if v.ok else tr('invalid')}")
        orig = next((m for m in self.project.markers if m.origin == "original"), None)
        if orig is not None and orig is not self.marker:
            so = marker_stats(self.project, orig)
            lines += ["", tr("compare"),
                      f"  length {so['length_mm']:.1f} → {s['length_mm']:.1f} mm ({s['length_mm'] - so['length_mm']:+.1f})",
                      f"  width {so['width_mm']:.0f} → {s['width_mm']:.0f} mm",
                      f"  utilisation {so['efficiency_total_width_pct']:.2f} → {s['efficiency_total_width_pct']:.2f} %",
                      f"  pieces {so['placed']} → {s['placed']}"]
        if self.project.sbinfo:
            lines += ["", "GRAFIS: " + ", ".join(f"{k}={self.project.sbinfo[k]}" for k in
                                                 ("WIDTH", "LENGTH", "EFFCNCY", "USDAREA", "PCSTOTAL", "MODEL")
                                                 if k in self.project.sbinfo)]
        self.results_text.setPlainText("\n".join(lines))

    # -- manual editing --------------------------------------------------------------------
    def on_moved(self, moves):
        if not self.marker:
            return
        changes = []
        for pl, dx, dy in moves:
            if pl.pinned:
                continue
            old = PlacementStateCommand.state(pl)
            new = (pl.x + dx, pl.y + dy) + old[2:]
            changes.append((pl, old, new))
        if changes:
            self.marker.origin = "manual" if self.marker.origin != "original" else "original"
            self.undo.push(PlacementStateCommand(self, changes, "move"))
        else:
            self.view.refresh()

    def rotate_selected(self):
        if not self.marker:
            return
        changes = []
        for pl in self.view.selected_placements():
            if pl.pinned:
                continue
            g = self.project.piece(pl.piece_uid).sizes[pl.size]
            b0 = bbox(placement_points(g.cut, pl))
            tmp = copy.copy(pl)
            tmp.rotation = (pl.rotation + 180.0) % 360.0
            tmp.x = tmp.y = 0.0
            b1 = bbox(placement_points(g.cut, tmp))
            cx, cy = (b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2
            nx, ny = cx - (b1[0] + b1[2]) / 2, cy - (b1[1] + b1[3]) / 2
            changes.append((pl, PlacementStateCommand.state(pl), (nx, ny, tmp.rotation, pl.mirrored, pl.pinned)))
        if changes:
            self.undo.push(PlacementStateCommand(self, changes, "rotate 180"))

    def pin_selected(self):
        if not self.marker:
            return
        changes = [(pl, PlacementStateCommand.state(pl), PlacementStateCommand.state(pl)[:4] + (not pl.pinned,))
                   for pl in self.view.selected_placements()]
        if changes:
            self.undo.push(PlacementStateCommand(self, changes, "pin"))

    def toggle_measure(self, on):
        self.view.measure_mode = on
        self.view.setDragMode(self.view.NoDrag if on else self.view.RubberBandDrag)
        if on:
            self.statusBar().showMessage(tr("measure_hint"))

    def view_opts(self):
        self.view.options.update(seam=self.act_seam.isChecked(), internal=self.act_int.isChecked(),
                                 grain=self.act_grain.isChecked(), labels=self.act_labels.isChecked(),
                                 color_by="size" if self.act_color.isChecked() else "piece")
        self.view.refresh()

    # -- nesting ---------------------------------------------------------------------------
    def run_nesting(self):
        if not self.project or (self.worker and self.worker.isRunning()):
            return
        self.read_tables()
        fabric = self.fabric_from_form()
        st = self.nest_settings_from_form()
        self.project.nest_settings = st
        pinned = [copy.copy(pl) for pl in (self.marker.placements if self.marker else [])
                  if pl.pinned and pl.placed and self.marker.origin != "original"]
        self.worker = NestWorker(self.project, fabric, st, self.project.cut_order, pinned)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(lambda e: (self._nest_ui(False), QMessageBox.critical(self, tr("run"), e)))
        self._nest_ui(True)
        self.worker.start()

    def _nest_ui(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.progress_bar.setVisible(running)
        self.progress_bar.setRange(0, 0 if running else 1)

    def stop_nesting(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()

    def on_progress(self, d):
        self.statusBar().showMessage(tr("running", len=d["length"], ev=d["evaluations"], t=d["elapsed"]))
        r = d.get("result")
        if r is not None and not d.get("final"):
            tmp = Marker(name="(running)", fabric=self.fabric_from_form(), placements=r.placements, length=r.length)
            self.view.show_marker(self.project, tmp)

    def on_finished(self, marker, info):
        self._nest_ui(False)
        self.project.markers.append(marker)
        self.refresh_markers_list(select=len(self.project.markers) - 1)
        v = info["validation"]
        msg = tr("done", v=v.summary())
        if info.get("warnings"):
            msg += " | " + "; ".join(info["warnings"])
        self.statusBar().showMessage(msg)

    # -- export ----------------------------------------------------------------------------
    def export(self, fmt):
        if not self.marker:
            return
        v = self.validate_current()
        if v is not None and not v.ok:
            if QMessageBox.question(self, tr("export"), v.summary() + "\n\nExport anyway?") != QMessageBox.Yes:
                return
        from ..exporters.iso import MachineProfile
        from ..exporters.plt import PlotterConfig
        from ..service import export_marker
        diagnostic = False
        cfg = None
        if fmt == "iso":
            prof = MachineProfile(**self.project.export_configs.get("iso", {})) if self.project.export_configs.get(
                "iso") else MachineProfile()
            if not prof.verified:
                if QMessageBox.question(self, tr("export_iso"), tr("not_configured_iso")) != QMessageBox.Yes:
                    return
                diagnostic = True
            cfg = prof
        elif fmt == "plt":
            cfg = PlotterConfig(**self.project.export_configs.get("plt", {})) if self.project.export_configs.get(
                "plt") else PlotterConfig()
        ext = {"plt": "PLT (*.plt)", "dxf": "DXF (*.dxf)", "iso": "ISO (*.iso)"}[fmt]
        name = f"{self.project.name}_{self.marker.fabric.width:g}{'_DIAGNOSTIC' if diagnostic else ''}.{fmt}"
        p, _ = QFileDialog.getSaveFileName(self, tr("export"),
                                           os.path.join(self.settings_store.value("export_dir", ""), name), ext)
        if not p:
            return
        try:
            export_marker(self.project, self.marker, fmt, p, cfg, diagnostic_iso=diagnostic)
        except Exception as e:
            QMessageBox.critical(self, tr("export"), str(e))
            return
        self.settings_store.setValue("export_dir", os.path.dirname(p))
        self.statusBar().showMessage(tr("exported", p=p))

    def plotter_settings(self):
        from dataclasses import asdict

        from ..exporters.plt import PlotterConfig
        if not self.project:
            return
        cfg = PlotterConfig(**self.project.export_configs.get("plt", {})) if self.project.export_configs.get(
            "plt") else PlotterConfig()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("plotter_settings"))
        f = QFormLayout(dlg)
        upm = self._dspin(1, 1000, cfg.units_per_mm, 3)
        swap = QCheckBox()
        swap.setChecked(cfg.swap_xy)
        fx = QCheckBox()
        fx.setChecked(cfg.flip_x)
        fy = QCheckBox()
        fy.setChecked(cfg.flip_y)
        txt = QCheckBox()
        txt.setChecked(cfg.include_text)
        pens = {}
        f.addRow("units per mm", upm)
        f.addRow("swap X/Y", swap)
        f.addRow("flip X", fx)
        f.addRow("flip Y", fy)
        f.addRow("labels (LB)", txt)
        for layer in ("CUT", "NOTCH", "SEAM", "INTERNAL", "GRAIN", "TEXT", "MARK", "BORDER"):
            s = QSpinBox()
            s.setRange(0, 8)
            s.setValue(cfg.pens.get(layer, 0))
            pens[layer] = s
            f.addRow(f"pen {layer} (0 = off)", s)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            cfg.units_per_mm, cfg.swap_xy, cfg.flip_x, cfg.flip_y = upm.value(), swap.isChecked(), fx.isChecked(), fy.isChecked()
            cfg.include_text = txt.isChecked()
            cfg.pens = {k: s.value() for k, s in pens.items()}
            self.project.export_configs["plt"] = asdict(cfg)

    def about(self):
        QMessageBox.information(self, tr("about"), (
            f"LEVEL7 Nesting {__version__}\n\n"
            "GRAFIS MDL/SCB: native reading of block structure, part list, sizes, evaluated geometry per size "
            "and SCB placements (no GRAFIS installation required). See docs/SUPPORT_STATUS.md.\n"
            "Not supported: writing MDL/SCB; spline definitions; symbol meanings.\n"
            "ISO: not configured for a specific machine (diagnostic preview only).\n"
            "Nesting results are heuristic; no global optimum is claimed."))

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            self.worker.wait(15000)
        super().closeEvent(ev)


_ = (math, QAbstractItemView)
