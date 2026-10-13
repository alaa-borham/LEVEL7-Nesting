"""Main window of the LEVEL7 Nesting desktop application."""
from __future__ import annotations

import copy
import math
import os
import threading
import traceback

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..geometry import bbox, lay_direction, placement_points
from ..model import FabricSettings, LayType, Marker, NestSettings, Placement, Project
from ..validation.checker import marker_stats, validate_marker
from .i18n import LANG, tr
from .marker_view import MarkerView
from .piece_strip import make_strip_area
from .updates import UpdateManager


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
        self.undo.setUndoLimit(500)
        self.setAcceptDrops(True)
        self.resize(1400, 860)
        self.view = MarkerView(self)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.view, 1)
        self.info_bar = self._make_info_bar()
        cl.addWidget(self.info_bar)
        self.setCentralWidget(central)
        self.view.moved.connect(self.on_moved)
        self.view.cursor_mm.connect(lambda x, y: self.coord_label.setText(f"x {x:.1f}  y {y:.1f} mm"))
        self.view.measured.connect(lambda d: self.statusBar().showMessage(tr("distance", d=d)))
        self._build_docks()
        self._build_actions()
        self.coord_label = QLabel()
        self.grafis_status = QLabel()
        self._load_display_options()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.hide()
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.grafis_status)
        self.statusBar().addPermanentWidget(self.coord_label)
        self.updates = None
        if not os.environ.get("LEVEL7_NO_UPDATE_CHECK"):
            self.updates = UpdateManager(self, self.settings_store, self._before_update)
            self.act_auto_upd.setChecked(self.updates.auto_enabled())
        else:
            self.act_auto_upd.setEnabled(False)
        self.retranslate()

    def check_updates(self):
        if self.updates:
            self.updates.check(True)

    def _set_auto_updates(self, on):
        if self.updates:
            self.updates.set_auto(on)

    def _before_update(self) -> bool:
        if self.worker and self.worker.isRunning():
            self.stop_nesting()
            self.worker.wait(15000)
        if self.project is None:
            return True
        r = QMessageBox.question(self, tr("updates"), tr("upd_save_first"),
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Yes:
            if self.project_path:
                self.save()
            else:
                self.save_as()
                if not self.project_path:
                    return False
        return True

    # -- construction --------------------------------------------------------------------
    def _build_docks(self):
        self.pieces_table = QTableWidget(0, 7)
        self.pieces_table.verticalHeader().hide()
        self.pieces_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.pieces_table.itemChanged.connect(
            lambda it: self._refresh_material_groups() if it.column() == 0 else None)
        self.sizes_table = QTableWidget(0, 2)
        self.sizes_table.verticalHeader().hide()
        left = QTabWidget()
        left.addTab(self.pieces_table, "")
        left.addTab(self.sizes_table, "")
        self.left_tabs = left
        self.dock_left = QDockWidget(self)
        self.dock_left.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_left)
        self.dock_left.setObjectName("pieces_table")
        self.dock_left.hide()            # replaced by the GRAFIS-like strip on top (View menu / double-click)

        # GRAFIS-like piece strip above the marker
        self.strip_area, self.strip = make_strip_area(self)
        self.strip_area.setMinimumHeight(40)
        self.strip.open_table.connect(lambda: (self.dock_left.show(), self.dock_left.raise_()))
        self.dock_strip = QDockWidget(self)
        self.dock_strip.setObjectName("piece_strip")
        self.dock_strip.setWidget(self.strip_area)
        self.dock_strip.setTitleBarWidget(QWidget())
        self.dock_strip.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.TopDockWidgetArea, self.dock_strip)

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
        self.f_time.setValue(120)
        self.f_engine = QComboBox()
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
                         ("max_len", self.f_maxlen), ("material", self.f_material), ("mode", self.f_mode), ("engine", self.f_engine),
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
        self.m_view.addAction(self._act("display_options", self.display_options, "Ctrl+D"))
        self.m_theme = self.m_view.addMenu("")
        from PySide6.QtGui import QActionGroup
        grp = QActionGroup(self)
        self.theme_actions = {}
        cur = str(self.settings_store.value("theme", "dark"))
        for key in ("light", "dark", "gray"):
            a = self._act("theme_" + key, lambda checked=False, k=key: self.set_theme(k), checkable=True,
                          checked=(key == cur))
            grp.addAction(a)
            self.m_theme.addAction(a)
            self.theme_actions[key] = a
        self.m_view.addSeparator()
        self.act_table = self.dock_left.toggleViewAction()
        self.m_view.addAction(self.act_table)
        self.m_nest.addAction(self._act("run", self.run_nesting, "F5"))
        self.m_nest.addAction(self._act("stop", self.stop_nesting, "Esc"))
        self.m_export.addAction(self._act("export_plt", lambda: self.export("plt")))
        self.m_export.addAction(self._act("export_dxf", lambda: self.export("dxf")))
        self.m_export.addAction(self._act("export_iso", lambda: self.export("iso")))
        self.m_export.addSeparator()
        self.m_export.addAction(self._act("plotter_settings", self.plotter_settings))
        self.m_help.addAction(self._act("check_updates", self.check_updates))
        self.act_auto_upd = self._act("auto_updates", self._set_auto_updates, checkable=True, checked=True)
        self.m_help.addAction(self.act_auto_upd)
        self.m_help.addAction(self._act("compat_report", lambda: self.compatibility_report()))
        self.m_help.addAction(self._act("open_logs", self.open_logs))
        self.m_help.addSeparator()
        self.m_help.addAction(self._act("about", self.about))
        self._build_toolbar(undo, redo)

    TOOLBAR = (("open", "open"), ("save", "save"), None, ("undo", None), ("redo", None), None,
               ("rotate180", "rotate180"), ("pin", "pin"), ("measure", "measure"), None,
               ("zoom_fit", "zoom_fit"), ("display_options", "display"), None,
               ("tab_pieces", "pieces"), ("tab_sizes", "sizes"), None,
               ("run", "run"), ("stop", "stop"), None,
               ("export_plt", "plt"), ("export_dxf", "dxf"), ("export_iso", "iso"), None,
               ("language", "language"))

    def _build_toolbar(self, undo, redo):
        from PySide6.QtCore import QSize
        from .icons import icon
        tb = self.addToolBar("main")
        tb.setObjectName("main")
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setStyleSheet("QToolBar { spacing: 2px; padding: 2px 4px; }"
                         "QToolButton { padding: 2px 6px; min-width: 46px; }")
        acts = {k: a for a, k in self.actions_tr}
        acts["undo"], acts["redo"] = undo, redo
        acts["tab_pieces"] = self._act("tab_pieces", lambda: self.show_table_tab(0), checkable=True)
        acts["tab_sizes"] = self._act("tab_sizes", lambda: self.show_table_tab(1), checkable=True)
        self.tab_actions = (acts["tab_pieces"], acts["tab_sizes"])
        self.dock_left.visibilityChanged.connect(lambda _v: self._sync_tab_actions())
        self.left_tabs.currentChanged.connect(lambda _i: self._sync_tab_actions())
        self.toolbar_items = []
        for item in self.TOOLBAR:
            if item is None:
                tb.addSeparator()
                continue
            key, ic = item
            a = acts[key]
            a.setIcon(icon(ic or key))
            tb.addAction(a)
            self.toolbar_items.append((a, key))
        # theme switch: its own button at the far end of the toolbar (far left in Arabic)
        from PySide6.QtWidgets import QSizePolicy, QToolButton
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.theme_button = QToolButton()
        self.theme_button.setIcon(icon("theme"))
        self.theme_button.setIconSize(QSize(28, 28))
        self.theme_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.theme_button.setPopupMode(QToolButton.InstantPopup)
        self.theme_button.setMenu(self.m_theme)
        tb.addWidget(self.theme_button)
        self.toolbar = tb

    def show_table_tab(self, index: int):
        """Toolbar 'Pieces' / 'Size quantities': open the table on that tab; a second click closes it."""
        if self.dock_left.isVisible() and self.left_tabs.currentIndex() == index:
            self.dock_left.hide()
        else:
            self.left_tabs.setCurrentIndex(index)
            self.dock_left.show()
            self.dock_left.raise_()
        self._sync_tab_actions()

    def _sync_tab_actions(self):
        vis = self.dock_left.isVisible()
        for i, a in enumerate(getattr(self, "tab_actions", ())):
            a.setChecked(vis and self.left_tabs.currentIndex() == i)

    def set_theme(self, name):
        from .icons import icon
        from .themes import apply_theme
        apply_theme(name)
        self.settings_store.setValue("theme", name)
        for a, key in self.toolbar_items:
            a.setIcon(icon(dict((k, i) for k, i in (x for x in self.TOOLBAR if x)).get(key) or key))
        self.theme_button.setIcon(icon("theme"))
        self.toolbar.setStyleSheet(self.toolbar.styleSheet())   # re-polish with the new palette
        for w in QApplication.instance().allWidgets():
            w.update()
        self.view.apply_theme()
        self.strip.update()

    def _retranslate_toolbar(self):
        for a, key in self.toolbar_items:
            a.setIconText(tr("tb_" + key))
            sc = a.shortcut().toString(QKeySequence.NativeText)
            a.setToolTip(a.text().replace("&", "") + (f"  ({sc})" if sc else ""))

    def retranslate(self):
        rtl = LANG["current"] == "ar"
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.setWindowTitle(f"{tr('app_title')} {__version__}" + (f" — {self.project.name}" if self.project else ""))
        for a, k in self.actions_tr:
            a.setText(tr(k))
        self.undo_actions[0].setText(tr("undo"))
        self.undo_actions[1].setText(tr("redo"))
        self.act_table.setText(tr("pieces_table"))
        self._retranslate_toolbar()
        self.m_theme.setTitle(tr("theme"))
        self.theme_button.setText(tr("theme"))
        self.theme_button.setToolTip(tr("theme"))
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
        for c, k in enumerate(("col_use", "col_name", "col_mat", "col_sizes", "col_count", "col_mirror", "col_grain")):
            h = self.pieces_table.horizontalHeaderItem(c)
            if h is not None and k != "col_name":
                h.setToolTip(tr("tip_" + k))
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
        from ..nesting import sparrow
        cur = self.f_engine.currentIndex()
        self.f_engine.clear()
        self.f_engine.addItems([tr("engine_auto") + ("" if sparrow.available() else " — " + tr("not_available")),
                                tr("engine_builtin")])
        self.f_engine.setCurrentIndex(cur if cur >= 0 else (0 if sparrow.available() else 1))
        self.f_engine.setToolTip(tr("engine_tip"))
        if not self.project:
            self.statusBar().showMessage(tr("ready"))
        self.update_results()

    def _load_display_options(self):
        import json
        try:
            saved = json.loads(self.settings_store.value("display_options", "{}") or "{}")
            self.view.options.update({k: v for k, v in saved.items() if k in self.view.options})
        except (ValueError, TypeError):
            pass

    def toggle_language(self):
        LANG["current"] = "en" if LANG["current"] == "ar" else "ar"
        self.settings_store.setValue("lang", LANG["current"])
        self.retranslate()

    def _mode_changed(self, i):
        self.f_time.setValue({0: 10, 1: 120, 2: 300}.get(i, 120))

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
        compat = [i for i in issues if i.startswith("COMPAT:") or "geometry not available" in i]
        if compat and path.lower().endswith((".mdl", ".scb")):
            box = QMessageBox(QMessageBox.Warning, tr("compat_title"), tr("compat_text", n=len(compat)), parent=self)
            box.setDetailedText("\n".join(compat[:50]))
            rep = box.addButton(tr("compat_report"), QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is rep:
                self.compatibility_report(path)

    def compatibility_report(self, path=None):
        """Inspection report of a GRAFIS file (structure, sections, unknown parts) to send for support."""
        import json
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from ..diagnostics.inspector import inspect_file, to_markdown
        from .app import log_dir
        if path is None:
            src = self.project.sources[0].path if self.project and self.project.sources else ""
            path, _ = QFileDialog.getOpenFileName(self, tr("compat_report"), src, "GRAFIS (*.mdl *.scb *.MDL *.SCB)")
            if not path:
                return
        out = os.path.join(os.path.dirname(log_dir()), "reports")
        os.makedirs(out, exist_ok=True)
        rep = inspect_file(path)
        base = os.path.join(out, os.path.basename(path))
        with open(base + ".report.json", "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1, default=str)
        with open(base + ".report.md", "w", encoding="utf-8") as fh:
            fh.write(to_markdown(rep))
        QMessageBox.information(self, tr("compat_report"), tr("compat_saved", p=base + ".report.md"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def load_tables(self):
        p = self.project
        t = self.pieces_table
        t.setRowCount(0)
        co = p.cut_order
        all_mats = sorted({pc.material for pc in p.pieces if pc.material} | {"O", "F"})
        for pc in sorted(p.pieces, key=lambda q: (not q.production, q.number or 0)):
            r = t.rowCount()
            t.insertRow(r)
            use = QTableWidgetItem()
            n, m = co.piece_counts.get(pc.uid, (0, 0))
            use.setCheckState(Qt.Checked if (n or m) else Qt.Unchecked)
            use.setData(Qt.UserRole, pc.uid)
            t.setItem(r, 0, use)
            t.setItem(r, 1, QTableWidgetItem(f"{pc.number or ''} {pc.name}"))
            t.setItem(r, 2, QTableWidgetItem(""))
            mat = QComboBox()                       # material of the part: choose or type a new code
            mat.setEditable(True)
            mat.addItems(all_mats)
            mat.setCurrentText(pc.material or "")
            mat.setToolTip(tr("material_tip"))
            mat.currentTextChanged.connect(lambda _t: self._refresh_material_groups())
            t.setCellWidget(r, 2, mat)
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
        self._refresh_material_groups(co.material)

    def _refresh_material_groups(self, select=None):
        """Material to nest: the material codes used by the pieces of the file (as assigned in the pieces table),
        with the GRAFIS material name when the file has one (SCB: MATERIAL<code>) and the number of pieces."""
        counts: dict[str, int] = {}
        for r in range(self.pieces_table.rowCount()):
            w = self.pieces_table.cellWidget(r, 2)
            use = self.pieces_table.item(r, 0)
            if w is not None and w.currentText().strip() and use is not None and use.checkState() == Qt.Checked:
                counts[w.currentText().strip()] = counts.get(w.currentText().strip(), 0) + 1
        names = {k[len("MATERIAL"):]: v for k, v in ((self.project.sbinfo or {}) if self.project else {}).items()
                 if k.startswith("MATERIAL") and len(k) > len("MATERIAL")}
        cur = select if select is not None else self.f_material.currentData()
        self.f_material.blockSignals(True)
        self.f_material.clear()
        self.f_material.addItem(tr("mat_all"), "*")
        for code in sorted(counts):
            label = f"{code} — {names[code]}" if names.get(code) else code
            self.f_material.addItem(f"{label}   ({tr('n_pieces', n=counts[code])})", code)
        i = self.f_material.findData(cur)
        self.f_material.setCurrentIndex(i if i >= 0 else 0)
        self.f_material.blockSignals(False)

    def read_tables(self):
        p = self.project
        co = p.cut_order
        for r in range(self.pieces_table.rowCount()):
            uid = self.pieces_table.item(r, 0).data(Qt.UserRole)
            pc = p.piece(uid)
            use = self.pieces_table.item(r, 0).checkState() == Qt.Checked
            mat_w = self.pieces_table.cellWidget(r, 2)
            if mat_w is not None:
                pc.material = mat_w.currentText().strip() or None
            n = self.pieces_table.cellWidget(r, 4).value()
            m = self.pieces_table.cellWidget(r, 5).value()
            co.piece_counts[uid] = (n, m) if use else (0, 0)
            g = self.pieces_table.cellWidget(r, 6).value()
            pc.grain_angle = None if g < 0 else g
        co.size_quantities = {self.sizes_table.item(r, 0).text(): self.sizes_table.cellWidget(r, 1).value()
                              for r in range(self.sizes_table.rowCount())}
        mat = self.f_material.currentData()
        co.material = None if mat in ("*", "", None) else mat

    def fabric_from_form(self) -> FabricSettings:
        lay = [LayType.OPEN, LayType.FACE_TO_FACE, LayType.FOLDED][max(0, self.f_lay.currentIndex())]
        return FabricSettings(width=self.f_width.value(), margin_left=self.f_ml.value(), margin_right=self.f_mr.value(),
                              margin_start=self.f_ms.value(), margin_end=self.f_me.value(), spacing=self.f_sp.value(),
                              lay_type=lay, max_length=self.f_maxlen.value() or None)

    def nest_settings_from_form(self) -> NestSettings:
        return NestSettings(mode=["fast", "balanced", "long"][max(0, self.f_mode.currentIndex())],
                            engine="auto" if self.f_engine.currentIndex() <= 0 else "builtin",
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
        prev = self.marker
        if prev is not None and prev is not self.project.markers[i] and "length_mm" in (prev.stats or {}):
            self.view.last_result = (prev.stats["length_mm"], prev.stats["efficiency_total_width_pct"])
        self.marker = self.project.markers[i]
        self.undo.clear()
        if "efficiency_total_width_pct" not in (self.marker.stats or {}):
            self.marker.stats = {**(self.marker.stats or {}), **marker_stats(self.project, self.marker)}
        self.view.efficiency = self.marker.stats["efficiency_total_width_pct"]
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
        self.marker.stats = {**(self.marker.stats or {}), **marker_stats(self.project, self.marker)}
        self.marker.length = self.marker.stats["length_mm"]
        self.issues_list.clear()
        self.issues_list.addItems([i.message for i in v.issues][:500] or [v.summary()])
        self.unplaced_list.clear()
        for pl in self.marker.placements:
            if not pl.placed:
                self.unplaced_list.addItem(f"{self.project.piece(pl.piece_uid).name} {pl.size}"
                                           f"{' (M)' if pl.mirrored else ''}: {pl.reason}")
        self.view.efficiency = self.marker.stats["efficiency_total_width_pct"]
        self.view.refresh()
        self.update_results(v)
        self.update_status_line()
        if fit:
            self.view.zoom_fit()

    def _refresh_strip(self):
        self.strip.set_data(self.project, self.marker)
        from .piece_strip import ROW_H, TOP
        rows = max(1, len(self.strip.rows))
        extra = 16 if rows > 2 or self.strip.sizeHint().width() > self.strip_area.width() else 4   # scroll bars
        self.strip_area.setFixedHeight(TOP + min(rows, 2) * ROW_H + extra)

    def update_results(self, v=None):
        if not self.marker or not self.project:
            self.results_text.setPlainText("")
            self._refresh_strip()
            return
        self._refresh_strip()
        s = self.marker.stats or marker_stats(self.project, self.marker)
        lines = [f"{tr('width')}: {s['width_mm']:.1f}  ({s['usable_width_mm']:.1f} usable)",
                 f"Length: {s['length_mm']:.1f} mm", f"Placed / unplaced: {s['placed']} / {s['unplaced']}",
                 f"Pieces area: {s['pieces_area_m2']:.4f} m²",
                 f"Utilisation (total width): {s['efficiency_total_width_pct']:.2f} %",
                 f"Utilisation (usable width): {s['efficiency_usable_width_pct']:.2f} %",
                 f"Waste: {s['waste_pct']:.2f} %",
                 f"Consumption: {s['consumption_m']:.3f} m = {s['consumption_yd']:.3f} yd",
                 f"Per garment (U/B): {s.get('length_per_garment_m', 0):.3f} m ({s.get('garments', 0)} garments)",
                 "By size: " + ", ".join(f"{k}: {n}" for k, n in sorted(s["by_size"].items()))]
        turned = total = 0
        pieces = {p.uid: p for p in self.project.pieces}
        for pl in self.marker.placements:
            pc = pieces.get(pl.piece_uid)
            d = lay_direction(pc.grain_angle, pl) if pc and pl.placed else None
            if d is not None:
                total += 1
                turned += d < 0
        if total:
            lines.append(tr("turned_180", n=turned, t=total))
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
        self.view.set_measure_mode(on)
        if on:
            self.statusBar().showMessage(tr("measure_hint"))

    def display_options(self):
        import json

        from .display_options import DisplayOptionsDialog
        dlg = DisplayOptionsDialog(self.view.options, self)
        if dlg.exec() == QDialog.Accepted:
            opts = dlg.result_options()
            self.settings_store.setValue("display_options", json.dumps(opts))
            self.view.set_options(**opts)
            self.update_status_line()

    INFO_FIELDS = ("L", "E", "U/B", "Wi", "Pc", "Mat")

    def _make_info_bar(self):
        """GRAFIS-like marker information directly under the marker."""
        bar = QWidget()
        bar.setObjectName("infobar")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(18)
        self.info_labels = {}
        for key in self.INFO_FIELDS:
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            f = lab.font()
            f.setPointSizeF(f.pointSizeF() + 1.5)
            lab.setFont(f)
            hl.addWidget(lab)
            self.info_labels[key] = lab
        hl.addStretch(1)
        return bar

    def _set_info(self, values: dict):
        for key, lab in self.info_labels.items():
            v = values.get(key)
            lab.setText(f"{key} = <b>{v}</b>" if v not in (None, "") else "")

    def update_status_line(self):
        """GRAFIS-style status: L, E, U/B, Wi (metres, or millimetres if chosen)."""
        if not self.marker or "length_mm" not in (self.marker.stats or {}):
            self.grafis_status.setText("")
            self._set_info({})
            return
        s = self.marker.stats
        mm = self.view.options.get("status_mm")
        f = (lambda v: f"{v:.1f} mm") if mm else (lambda v: f"{v / 1000:.2f} m")
        self.grafis_status.setText(f"L = {f(s['length_mm'])}   E = {s['efficiency_total_width_pct']:.1f} %   "
                                   f"U/B = {f(s.get('length_per_garment_m', 0) * 1000)}   Wi = {f(s['width_mm'])}")
        mats = sorted({(self.project.piece(pl.piece_uid).material or "?") for pl in self.marker.placements
                       if pl.placed and self.project.piece(pl.piece_uid)})
        self._set_info({"L": f(s["length_mm"]), "E": f"{s['efficiency_total_width_pct']:.1f} %",
                        "U/B": f(s.get("length_per_garment_m", 0) * 1000), "Wi": f(s["width_mm"]),
                        "Pc": f"{s['placed']} / {s['placed'] + s['unplaced']}", "Mat": ", ".join(mats)})

    # -- nesting ---------------------------------------------------------------------------
    def run_nesting(self):
        if not self.project or (self.worker and self.worker.isRunning()):
            return
        self.read_tables()
        if not self._check_cut_order():
            return
        if not self._ensure_geometry():
            return
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

    def _check_cut_order(self) -> bool:
        """Explain an empty cut order instead of failing: no size quantity, no piece, or the material filter."""
        co = self.project.cut_order
        sizes = [s for s, q in co.size_quantities.items() if q > 0]
        used = [p for p in self.project.pieces if sum(co.piece_counts.get(p.uid, (0, 0))) > 0]
        in_mat = [p for p in used if not co.material or p.material == co.material]
        reason = None
        if not self.project.pieces or not any(p.sizes for p in self.project.pieces):
            reason = tr("empty_no_geometry", n=len(self.project.pieces))
        elif not sizes:
            reason = tr("empty_no_sizes")
        elif not used:
            reason = tr("empty_no_pieces")
        elif not in_mat:
            reason = tr("empty_material", m=co.material)
        if reason is None:
            return True
        QMessageBox.information(self, tr("run"), reason)
        if not sizes or not used:
            self.dock_left.show()
            self.dock_left.raise_()
            self.left_tabs.setCurrentIndex(1 if not sizes else 0)
        return False

    def _ensure_geometry(self) -> bool:
        """Selected sizes without geometry (an SCB holds only some sizes): offer to load them from the MDL."""
        from ..service import missing_geometry, supplement_from_model
        co = self.project.cut_order
        sizes = [s for s, q in co.size_quantities.items() if q > 0]
        used = {u for u, (n, m) in co.piece_counts.items() if n + m > 0}
        miss = {s: [p.name for p in self.project.pieces if p.uid in used and s not in p.sizes] for s in sizes}
        miss = {s: v for s, v in miss.items() if v}
        if not miss:
            return True
        r = QMessageBox.question(self, tr("run"), tr("missing_sizes", s=", ".join(sorted(miss))),
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Yes:
            start = os.path.dirname(self.project.sources[0].path) if self.project.sources else ""
            path, _ = QFileDialog.getOpenFileName(self, tr("open"), start, "GRAFIS model (*.mdl *.MDL)")
            if not path:
                return False
            try:
                n = supplement_from_model(self.project, path)
            except Exception as exc:
                QMessageBox.warning(self, tr("run"), str(exc))
                return False
            self.statusBar().showMessage(tr("sizes_loaded", n=n, p=os.path.basename(path)))
            self.load_tables()
            self.read_tables()
            left = {s for s in sizes for p in self.project.pieces if p.uid in used and s not in p.sizes}
            if left:
                QMessageBox.warning(self, tr("run"), tr("missing_sizes_left", s=", ".join(sorted(left))))
        return True

    def _nest_ui(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.progress_bar.setVisible(running)
        self.progress_bar.setRange(0, 0 if running else 1)

    def stop_nesting(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()

    PREVIEW_INTERVAL_MS = 600

    def on_progress(self, d):
        """Live preview, coalesced: at most one redraw per PREVIEW_INTERVAL_MS however fast results arrive."""
        self.statusBar().showMessage(tr("running", len=d["length"], ev=d["evaluations"], t=d["elapsed"]))
        if d.get("result") is not None and not d.get("final"):
            first = getattr(self, "_pending_preview", None) is None
            self._pending_preview = d["result"]
            if first:
                QTimer.singleShot(self.PREVIEW_INTERVAL_MS, self._draw_preview)

    def _draw_preview(self):
        r, self._pending_preview = getattr(self, "_pending_preview", None), None
        if r is None or not (self.worker and self.worker.isRunning()):
            return
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
            from PySide6.QtWidgets import QInputDialog

            from ..exporters.iso import bullmer_grafis_profile, iecho_profile
            choices = [tr("iso_bullmer"), tr("iso_iecho"), tr("iso_diagnostic")]
            choice, ok = QInputDialog.getItem(self, tr("export_iso"), tr("iso_machine"), choices, 0, False)
            if not ok:
                return
            if choice in choices[:2]:
                prof = bullmer_grafis_profile() if choice == choices[0] else iecho_profile()
                if not prof.device_tested and QMessageBox.question(
                        self, tr("export_iso"), tr("iso_not_device_tested")) != QMessageBox.Yes:
                    return
            else:
                prof = MachineProfile()
                if QMessageBox.question(self, tr("export_iso"), tr("not_configured_iso")) != QMessageBox.Yes:
                    return
                diagnostic = True
            cfg = prof
        elif fmt == "plt":
            cfg = self.plt_config()
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

    def plt_config(self):
        from ..exporters.plt import PlotterConfig
        from .plot_settings import default_config
        raw = self.project.export_configs.get("plt") if self.project else None
        return PlotterConfig(**raw) if raw else default_config(self.settings_store)

    def plotter_settings(self):
        import json
        from dataclasses import asdict
        from .plot_settings import SETTINGS_KEY, PlotSettingsDialog
        dlg = PlotSettingsDialog(self, self.plt_config())
        if dlg.exec() == QDialog.Accepted:
            cfg = asdict(dlg.result_config())
            self.settings_store.setValue(SETTINGS_KEY, json.dumps(cfg))     # default for every project
            if self.project:
                self.project.export_configs["plt"] = cfg

    def open_logs(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from .app import log_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))

    def about(self):
        QMessageBox.information(self, tr("about"), (
            f"LEVEL7 Nesting {__version__}\n\n"
            "GRAFIS MDL/SCB: native reading of block structure, part list, sizes, evaluated geometry per size "
            "and SCB placements (no GRAFIS installation required). See docs/SUPPORT_STATUS.md.\n"
            "Not supported: writing MDL/SCB; spline definitions.\n"
            "ISO: Bullmer / IECHO profile matched to GRAFIS' Bullmer output; test-cut before production.\n"
            "Updates: GitHub Releases (alaa-borham/LEVEL7-Nesting), SHA-256 verified.\n"
            "Nesting results are heuristic; no global optimum is claimed."))

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            self.worker.wait(15000)
        super().closeEvent(ev)


_ = (math, QAbstractItemView)
