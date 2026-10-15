"""Main window of the LEVEL7 Nesting desktop application."""
from __future__ import annotations

import copy
import math
import os
import threading
import time
import traceback

from PySide6.QtCore import QEvent, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..geometry import bbox, lay_direction, placement_points
from ..model import FabricSettings, LayType, Marker, NestSettings, Placement, Project
from ..validation.checker import marker_stats, validate_marker
from .i18n import LANG, T, tr
from .marker_view import MarkerView
from .piece_strip import make_strip_area
from .updates import UpdateManager


# ---------------------------------------------------------------------------------- undo
def _owned_by(w, owner) -> bool:
    """w lives in a pop-up list that belongs to owner (e.g. the list of a combo box inside a panel)."""
    p = w
    while p is not None:
        if p is owner:
            return True
        p = p.parentWidget()
    return False


TAKEN_OUT = "taken out of the marker"      # Placement.reason of copies the user removed from the marker


ORPHAN_WORKERS: list = []        # runs still going when their window closed (see closeEvent / app.main)


def _nest_log(msg: str) -> None:
    """One line per nesting event in logs/nest.log (start / stop / end) - to follow a run on the user's machine."""
    try:
        from .app import log_dir
        with open(os.path.join(log_dir(), "nest.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


class OrderSyncCommand(QUndoCommand):
    """The marker's copies changed with the order (MainWindow._sync_marker): undo brings the old list back."""

    def __init__(self, window, marker, old, new):
        super().__init__("order")
        self.window, self.marker, self.old, self.new = window, marker, old, new

    def _set(self, pls):
        self.marker.placements = list(pls)
        if self.window.marker is self.marker:
            self.window._redraw_marker()
            self.window._refresh_strip()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class PlacementStateCommand(QUndoCommand):
    def __init__(self, window, changes, text):
        super().__init__(text)
        self.window = window
        self.changes = changes  # [(placement, old_state, new_state)]

    @staticmethod
    def state(pl: Placement):
        return (pl.x, pl.y, pl.rotation, pl.mirrored, pl.pinned, pl.placed, pl.reason)

    @staticmethod
    def apply(pl, st):
        pl.x, pl.y, pl.rotation, pl.mirrored, pl.pinned, pl.placed, pl.reason = st

    def _done(self):
        if any(o[5] != n[5] for _pl, o, n in self.changes):      # a piece left / came back: redraw the marker
            self.window._redraw_marker()
        else:
            self.window.after_edit()

    def redo(self):
        for pl, _o, n in self.changes:
            self.apply(pl, n)
        self._done()

    def undo(self):
        for pl, o, _n in self.changes:
            self.apply(pl, o)
        self._done()


# -------------------------------------------------------------------------------- worker
# nesting runs share the processor (level7.nesting.slots): at most "simultaneous nestings" runs work at once,
# each on its share of the cores; later runs wait for a slot and their time limit starts when they start.
from ..nesting.slots import NEST_SLOTS


class NestWorker(QThread):
    progress = Signal(dict)
    finished_ok = Signal(object, dict)
    failed = Signal(str)
    waiting = Signal(bool)          # True: queued behind another session's run; False: started
    cancelled = Signal()            # stopped while still waiting

    def __init__(self, project, fabric, settings, cut_order, pinned, placements=None, keep_out=None):
        super().__init__()
        self.project, self.fabric, self.settings = project, fabric, settings
        self.cut_order, self.pinned = cut_order, pinned
        self.placements, self.keep_out = placements, keep_out
        self.stop_event = threading.Event()

    def run(self):
        queued = False
        while not NEST_SLOTS.acquire(timeout=0.3):
            if not queued:
                queued = True
                self.waiting.emit(True)
            if self.stop_event.is_set():
                self.cancelled.emit()
                return
        try:
            if queued:
                self.waiting.emit(False)
            self._run()
        finally:
            NEST_SLOTS.release()

    def _run(self):
        from ..service import run_nesting
        try:
            marker, info = run_nesting(self.project, self.fabric, self.settings, self.cut_order, self.pinned,
                                       progress=lambda d: self.progress.emit(d), stop_event=self.stop_event,
                                       placements=self.placements, keep_out=self.keep_out,
                                       workers=NEST_SLOTS.workers())
            self.finished_ok.emit(marker, info)
        except Exception as e:
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, sessions=None, primary: bool = True):
        super().__init__()
        self.sessions = sessions          # SessionManager (several windows), None when used stand-alone
        self.settings_store = QSettings("LEVEL7", "Nesting")
        from .wheel_guard import install as _wheel_guard
        _wheel_guard()                            # the mouse wheel never changes a table value by accident
        LANG["current"] = self.settings_store.value("lang", "ar")
        self.project: Project | None = None
        self.project_path: str | None = None
        self.marker: Marker | None = None
        self.worker: NestWorker | None = None
        self._sync_spare: dict = {}        # marker id -> copies removed by order changes (see _sync_marker)
        self.dirty = False                # unsaved changes in this session
        self.undo = QUndoStack(self)
        self.undo.indexChanged.connect(lambda _i: self.mark_dirty())
        self.undo.setUndoLimit(500)
        self.setAcceptDrops(True)
        self.resize(1400, 860)
        self.view = MarkerView(self)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.view, 1)
        self.setCentralWidget(central)
        self.view.moved.connect(self.on_moved)
        self.view.scene().selectionChanged.connect(self._marker_selection_changed)
        self.view.dragging.connect(self._live_length)
        self.view.piece_dropped.connect(self.place_from_strip)
        self.view.measured.connect(lambda d: self.statusBar().showMessage(tr("distance", d=d)))
        self._build_docks()
        self._build_actions()
        from .status_bar import StatusBar
        self.setStatusBar(StatusBar(self))
        from .status_bar import StatChips
        self.grafis_status = StatChips()            # L / E / U/B / Wi, each in its own box
        self._load_display_options()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setMinimumWidth(60)
        self.progress_bar.hide()
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.grafis_status)
        self.updates = None
        if primary and not os.environ.get("LEVEL7_NO_UPDATE_CHECK"):
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
        """Every session window: stop nesting / batch, offer to save; then they close without asking again."""
        wins = self._all_windows()
        for w in wins:
            if w.worker and w.worker.isRunning():
                w.worker.stop_event.set()
                w.worker.wait()
            dlg = getattr(w, "_batch_dlg", None)
            try:
                if dlg is not None:
                    dlg.stop_and_wait()
            except RuntimeError:
                pass
        for w in wins:
            if w.project is None or not w.dirty:
                continue
            w.raise_()
            r = QMessageBox.question(w, tr("updates"), tr("upd_save_first"),
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Yes and not w.save():
                return False
        for w in wins:
            w._closing_for_update = True
        return True

    # -- construction --------------------------------------------------------------------
    def _build_docks(self):
        self.pieces_table = QTableWidget(0, 7)
        self.pieces_table.verticalHeader().hide()
        # a selected piece = its whole row highlighted, the field boxes in the row included
        self.pieces_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        from .row_select import RowSelect
        self._row_select = RowSelect(self.pieces_table)
        self.pieces_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.pieces_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pieces_table.customContextMenuRequested.connect(self._pieces_menu)
        self.pieces_table.itemChanged.connect(
            lambda it: (self._refresh_material_groups(), self._table_edited()) if it.column() == 0 else None)
        self.sizes_table = QTableWidget(0, 2)
        self.sizes_table.verticalHeader().hide()
        self.sizes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        # each table drops down under its own toolbar icon ("Pieces" / "Sizes")
        from PySide6.QtCore import QSize
        from .table_popup import TablePopup
        self.pieces_popup = TablePopup(self, self.pieces_table, QSize(980, 460))
        self.sizes_popup = TablePopup(self, self.sizes_table, QSize(380, 440))
        self.table_popups = (self.pieces_popup, self.sizes_popup)

        # GRAFIS-like piece strip above the marker
        self.strip_area, self.strip = make_strip_area(self)
        self.strip_area.setMinimumHeight(40)
        self.strip.open_table.connect(lambda: self.show_table_tab(0))
        self.strip.row_toggled.connect(self._toggle_strip_row)
        self.strip.relayout.connect(self._strip_height)
        self.strip.piece_clicked.connect(lambda uid: self._highlight_pieces({uid}))
        self.dock_strip = QDockWidget(self)
        self.dock_strip.setObjectName("piece_strip")
        self.dock_strip.setWidget(self.strip_area)
        self.dock_strip.setTitleBarWidget(QWidget())
        self.dock_strip.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.TopDockWidgetArea, self.dock_strip)

        # fabric / nesting form
        w = QWidget()
        self.form = QFormLayout(w)
        # defaults = the settings that gave good results in the user's production (10/2026): width 1480 mm,
        # long search, 120 s, seed 2, 180 deg allowed, tolerance 0.20 mm, 3 attempts ("best result")
        self.f_width = self._dspin(100, 10000, 1480)
        self.f_ml = self._dspin(0, 500, 0)
        self.f_mr = self._dspin(0, 500, 0)
        self.f_ms = self._dspin(0, 2000, 0)
        self.f_me = self._dspin(0, 2000, 0)
        self.f_sp = self._dspin(0, 50, 0)
        self.f_bx = self._dspin(0, 100, 0)
        self.f_by = self._dspin(0, 100, 0)
        self.f_shx = self._dspin(-20, 20, 0, 2)
        self.f_shy = self._dspin(-20, 20, 0, 2)
        self.f_lay = QComboBox()
        self.f_maxlen = self._dspin(0, 100000, 0)
        for f in (self.f_width, self.f_ml, self.f_mr, self.f_ms, self.f_me, self.f_sp, self.f_bx, self.f_by,
                  self.f_maxlen):
            f.setSuffix(" mm")
        for f in (self.f_shx, self.f_shy):
            f.setSuffix(" %")
        self.f_mode = QComboBox()
        self.f_time = QSpinBox()
        self.f_time.setRange(1, 7200)
        self.f_time.setValue(120)
        self.f_engine = QComboBox()
        self.f_seed = QSpinBox()
        self.f_seed.setRange(0, 2 ** 31 - 1)
        self.f_seed.setValue(2)
        self.f_rot180 = QCheckBox()
        self.f_rot180.setChecked(True)
        self.f_rot90 = QCheckBox()
        self.f_tol = self._dspin(0.01, 2.0, 0.2, 2)
        # application-wide: how many nestings may run at the same time (cores are divided between them)
        self.f_best = QSpinBox()                   # "best result": attempts with different seeds, shortest wins
        self.f_best.setRange(1, 10)
        self.f_best.setValue(3)
        self.f_parallel = QSpinBox()
        self.f_parallel.setRange(1, 16)
        try:
            lim = int(self.settings_store.value("parallel_nests", 0) or 0)
        except (TypeError, ValueError):
            lim = 0
        self.f_parallel.setValue(lim or 1)    # default: one nesting at a time, with all the cores (shortest markers)
        NEST_SLOTS.set_limit(self.f_parallel.value())
        self.f_parallel.valueChanged.connect(self._set_parallel)
        self.f_material = QComboBox()
        self.form_rows = []
        self.form_fields = {}
        self.form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.form.setHorizontalSpacing(6)
        self.form.setVerticalSpacing(3)
        # margins, buffers and shrinkage: own toolbar icon with a drop-down panel (like Pieces / Sizes)
        mw = QWidget()
        self.form_spacing = QFormLayout(mw)
        self.form_spacing.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.form_spacing.setHorizontalSpacing(6)
        self.form_spacing.setVerticalSpacing(3)
        for key, wid in (("spacing", self.f_sp), ("margin_l", self.f_ml), ("margin_r", self.f_mr), ("margin_s", self.f_ms),
                         ("margin_e", self.f_me), ("buffer_x", self.f_bx),
                         ("buffer_y", self.f_by), ("shrink_x", self.f_shx), ("shrink_y", self.f_shy)):
            lab = QLabel()
            wid.setFixedWidth(140)
            self.form_spacing.addRow(lab, wid)
            self.form_fields[key] = wid
            self.form_rows.append((lab, key))
        from PySide6.QtCore import QSize as _QSize
        from .table_popup import TablePopup
        self.spacing_popup = TablePopup(self, mw, _QSize(320, 330))
        self.table_popups = self.table_popups + (self.spacing_popup,)
        # plaid / stripe matching: fabric repeat + match point per piece
        from .plaid_panel import PlaidPanel
        self.plaid = PlaidPanel()
        self.plaid_popup = TablePopup(self, self.plaid, _QSize(560, 420))
        self.plaid.fabric_changed.connect(self._plaid_fabric_changed)
        self.plaid.rules_changed.connect(self._plaid_rules_changed)
        self.plaid.pick_toggled.connect(self._plaid_pick)
        self.view.match_picked.connect(self._match_picked)
        self.view.pick_finished.connect(lambda: self.plaid.b_pick.setChecked(False))
        for key, wid in (("width", self.f_width), ("lay", self.f_lay),
                         ("max_len", self.f_maxlen), ("material", self.f_material), ("mode", self.f_mode), ("engine", self.f_engine),
                         ("time", self.f_time), ("seed", self.f_seed), ("rot180", self.f_rot180),
                         ("rot90", self.f_rot90), ("tolerance", self.f_tol), ("best_of", self.f_best),
                         ("parallel", self.f_parallel)):
            lab = QLabel()
            if not isinstance(wid, QCheckBox):
                wid.setFixedWidth(140)           # compact panel: full explanations are in the tooltips
            self.form.addRow(lab, wid)
            self.form_fields[key] = wid
            self.form_rows.append((lab, key))
        self.f_mode.currentIndexChanged.connect(self._mode_changed)
        btns = QHBoxLayout()
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("primary")
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_run.clicked.connect(lambda: self.run_nesting())
        self.btn_stop.clicked.connect(self.stop_nesting)
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_stop)
        self.form.addRow(btns)
        # nesting properties: drop-down panel under the toolbar icon "Properties" (more room for the marker)
        self.props_popup = TablePopup(self, w, _QSize(330, 420))
        self.table_popups = self.table_popups + (self.props_popup, self.plaid_popup)
        self.btn_run.clicked.connect(self.props_popup.hide)

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
        # results: drop-down under the toolbar icon "Results" (the marker gets the full width)
        self.results_popup = TablePopup(self, r, _QSize(460, 640))
        self.table_popups = self.table_popups + (self.results_popup,)

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
        self.m_file.addAction(self._act("new_session", self.new_session, "Ctrl+N"))
        self.m_file.addAction(self._act("add_model", self.add_model_dialog, "Ctrl+Shift+O"))
        self.m_file.addAction(self._act("save", self.save, "Ctrl+S"))
        self.m_file.addAction(self._act("save_as", self.save_as, "Ctrl+Shift+S"))
        self.m_file.addAction(self._act("save_scb", lambda: self.export("scb"), "Ctrl+Alt+S"))
        self.m_file.addAction(self._act("save_mdl", self.save_mdl_as))
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
        self.m_edit.addAction(self._act("take_out", self.take_out_selected, "Delete"))
        self.act_measure = self._act("measure", self.toggle_measure, "M", checkable=True)
        self.m_edit.addAction(self.act_measure)
        self.act_measure_curve = self._act("measure_curve", self.toggle_measure_curve, "Shift+M", checkable=True)
        self.m_edit.addAction(self.act_measure_curve)
        self.m_view.addAction(self._act("zoom_fit", self.view.zoom_fit, "F"))
        # zoom shortcuts (+ / - also on the number pad) and the marker over the whole screen (F11, Esc = back)
        for key, fn, keys in (("zoom_in", lambda: self.view.zoom_step(1.25), ("Ctrl++", "Ctrl+=", "+")),
                              ("zoom_out", lambda: self.view.zoom_step(0.8), ("Ctrl+-", "-")),
                              ("marker_full", self.toggle_marker_full, ("F11",))):
            a = self._act(key, fn)
            a.setShortcuts([QKeySequence(k) for k in keys])
            self.m_view.addAction(a)
            self.addAction(a)                     # keeps working while the menu bar is hidden (full screen)
        self.act_marker_full = a
        self.act_marker_full.setCheckable(True)
        self._act_full_exit = QAction(self)
        self._act_full_exit.setShortcut(QKeySequence("Esc"))
        self._act_full_exit.triggered.connect(lambda: self._marker_full and self.toggle_marker_full())
        self._act_full_exit.setEnabled(False)
        self.addAction(self._act_full_exit)
        self.m_view.addAction(self._act("display_options", self.display_options, "Ctrl+D"))
        self.m_view.addAction(self._act("tb_customize", lambda: self.customize_toolbar()))
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
        self.m_nest.addAction(self._act("run", lambda: self.run_nesting(), "F5"))
        self.act_renest = self._act("renest_inside", lambda: self.renest_inside(), "Shift+F5")
        self.m_nest.addAction(self.act_renest)
        self.m_nest.addAction(self._act("stop", self.stop_nesting, "Esc"))
        self.m_nest.addSeparator()
        self.m_nest.addAction(self._act("batch", self.batch_dialog, "Ctrl+B"))
        self.m_export.addAction(self._act("export_plt", lambda: self.export("plt")))
        self.m_export.addAction(self._act("export_dxf", lambda: self.export("dxf")))
        self.m_export.addAction(self._act("export_iso", lambda: self.export("iso")))
        self.m_export.addAction(self._act("export_scb", lambda: self.export("scb")))
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

    TOOLBAR = (("open", "open"), ("add_model", "add_model"), ("save", "save"), None, ("undo", None), ("redo", None), None,
               ("rotate180", "rotate180"), ("pin", "pin"), ("measure_tool", "measure"), None,
               ("zoom_fit", "zoom_fit"), ("display_options", "display"), None,
               ("tab_props", "properties"), ("tab_results", "results"), ("tab_pieces", "pieces"), ("tab_sizes", "sizes"), ("tab_spacing", "margins"), ("tab_plaid", "plaid"), None,
               ("run", "run"), ("stop", "stop"), ("batch", "batch"), None,
               ("export_menu", "export"), None,
               ("language", "language"))

    def _build_toolbar(self, undo, redo):
        from PySide6.QtCore import QSize
        from .icons import icon
        tb = self.addToolBar("main")
        tb.setObjectName("main")
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        acts = {k: a for a, k in self.actions_tr}
        acts["undo"], acts["redo"] = undo, redo
        # one "Export" button: its menu holds PLT / DXF / ISO / GRAFIS SCB and the plotter settings
        acts["export_menu"] = self._act("export_menu", lambda: None)
        acts["export_menu"].setMenu(self.m_export)
        acts["tab_pieces"] = self._act("tab_pieces", lambda: self.show_table_tab(0), checkable=True)
        acts["tab_sizes"] = self._act("tab_sizes", lambda: self.show_table_tab(1), checkable=True)
        acts["tab_spacing"] = self._act("tab_spacing", lambda: self.show_table_tab(2), checkable=True)
        acts["tab_props"] = self._act("tab_props", lambda: self.show_table_tab(3), checkable=True)
        acts["tab_plaid"] = self._act("tab_plaid", lambda: self.show_table_tab(4), checkable=True)
        acts["tab_results"] = self._act("tab_results", lambda: self.show_table_tab(5), checkable=True)
        self.tab_actions = (acts["tab_pieces"], acts["tab_sizes"], acts["tab_spacing"], acts["tab_props"],
                            acts["tab_plaid"], acts["tab_results"])
        # one 'Measure' button: click = measure with the chosen kind, right-click = choose distance / curve
        acts["measure_tool"] = self.act_measure_tool = self._act("measure_tool", self.toggle_measure_tool,
                                                                 checkable=True)
        for pop in self.table_popups:
            pop.closed.connect(self._sync_tab_actions)
        self.m_view.addActions(list(self.tab_actions))
        self.toolbar_items = []
        self._tb_keys = {}                        # key -> action of every toolbar icon
        for item in self.TOOLBAR:
            if item is None:
                continue
            key, ic = item
            a = acts[key]
            a.setIcon(icon(ic or key))
            self._tb_keys[key] = a
            self.toolbar_items.append((a, key))
        self._tb_entries = self._entries_from_settings()
        from PySide6.QtWidgets import QMenu
        self._acts = acts
        self.m_measure = QMenu(self)
        self.m_measure.addAction(self.act_measure)
        self.m_measure.addAction(self.act_measure_curve)
        # Nest: right-click offers full nesting / re-nest only the pieces inside the marker
        self.m_run = QMenu(self)
        self.m_run.addAction(acts["run"])
        self.m_run.addAction(self.act_renest)
        self.act_best = self._act("best_result", lambda: self.run_nesting(best_of=max(3, self.f_best.value())),
                                  "Ctrl+F5")
        self.m_run.addAction(self.act_best)
        self.m_nest.addAction(self.act_best)
        # Save: right-click offers Save / Save as… (like Measure)
        self.m_save = QMenu(self)
        for a, k in self.actions_tr:
            if k in ("save", "save_as", "save_scb", "save_mdl"):
                self.m_save.addAction(a)
        self.measure_kind = "curve" if self.settings_store.value("measure_kind", "line") == "curve" else "line"
        # extra rows: used only when the window is too narrow for one row (icons wrap instead of hiding)
        rows = [tb]
        for k in (2, 3):
            self.addToolBarBreak(Qt.TopToolBarArea)
            t = self.addToolBar(f"main{k}")
            t.setObjectName(f"main{k}")
            t.setMovable(False)
            t.setIconSize(QSize(28, 28))
            t.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            rows.append(t)
        self.toolbar = tb
        self.toolbar2 = rows[1]
        self.toolbars = rows
        self._tb_split = None
        self._tb_widths: dict = {}
        self._layout_toolbar(force=True)
        QApplication.instance().installEventFilter(self)       # click outside an open panel closes it

    # -- toolbar order (customizable) -----------------------------------------------------------
    def _default_order(self):
        return ["|" if it is None else it[0] for it in self.TOOLBAR]

    def _entries_from_settings(self):
        """("act", action) / ("sep",) / ("theme",) in the user's order; icons added in a later version go last."""
        order = self.settings_store.value("toolbar_order", "") or ""
        hidden = set(filter(None, (self.settings_store.value("toolbar_hidden", "") or "").split(",")))
        keys = [k for k in order.split(",") if k == "|" or k in self._tb_keys] if order else self._default_order()
        keys += [k for k in self._default_order() if k != "|" and k not in keys]
        out = []
        for k in keys:
            if k == "|":
                if out and out[-1][0] != "sep":
                    out.append(("sep",))
            elif k not in hidden:
                out.append(("act", self._tb_keys[k]))
        while out and out[-1][0] == "sep":
            out.pop()
        return out + [("theme",)]

    def customize_toolbar(self):
        from .toolbar_dialog import ToolbarDialog
        order = self.settings_store.value("toolbar_order", "") or ",".join(self._default_order())
        hidden = set(filter(None, (self.settings_store.value("toolbar_hidden", "") or "").split(",")))
        keys = [k for k in order.split(",") if k == "|" or k in self._tb_keys]
        keys += [k for k in self._default_order() if k != "|" and k not in keys]
        dlg = ToolbarDialog(self, keys, self._tb_keys, hidden, self._default_order())
        if dlg.exec() != QDialog.Accepted:
            return
        keys, hidden = dlg.result_order()
        self.settings_store.setValue("toolbar_order", ",".join(keys))
        self.settings_store.setValue("toolbar_hidden", ",".join(sorted(hidden)))
        for w in self._all_windows():                 # every session window
            w._tb_entries = w._entries_from_settings()
            w._tb_split = None
            w._layout_toolbar(force=True)

    def contextMenuEvent(self, ev):
        """Right-click on an empty place of the toolbar: customize it."""
        if any(t.isVisible() and t.geometry().contains(ev.pos()) for t in self.toolbars):
            from PySide6.QtWidgets import QMenu
            m = QMenu(self)
            m.addAction(tr("tb_customize"), self.customize_toolbar)
            m.exec(ev.globalPos())
            return
        super().contextMenuEvent(ev)

    # -- toolbar wrapping ----------------------------------------------------------------------
    def _entry_width(self, e) -> int:
        if e[0] == "sep":
            return 14                                   # 2 px line + 6 px each side (themes.py)
        if e[0] == "theme":
            return 48
        a = e[1]
        w = self._tb_widths.get(id(a))
        if w is None:
            fm = self.toolbar.fontMetrics()
            w = max(40, fm.horizontalAdvance(a.iconText().replace("&", "")) + 12)
        return w + 1

    def _layout_toolbar(self, force=False):
        """Fill each toolbar row with as many icons as fit the window width (cut at a group separator when
        possible); further rows (up to 3) are shown only when needed."""
        if not hasattr(self, "toolbars") or getattr(self, "_marker_full", False):
            return
        if getattr(self, "_tb_slack_w", None) != self.width():
            # the correction below belongs to one window width: a margin kept from a smaller window (before it
            # was maximized) made the icons wrap into two rows on a wide screen
            self._tb_slack, self._tb_slack_w = 0, self.width()
            force = True
        avail = max(200, self.width() - 12 - getattr(self, "_tb_slack", 0))
        rows, cur, acc, last_sep = [], [], 0, None
        for e in self._tb_entries:
            w = self._entry_width(e)
            if acc + w > avail and cur and len(rows) < len(self.toolbars) - 1:
                if last_sep is not None and last_sep > len(cur) // 2:     # wrap at the group boundary
                    rows.append(cur[:last_sep])
                    cur = cur[last_sep + 1:]
                else:
                    rows.append(cur)
                    cur = []
                acc = sum(self._entry_width(x) for x in cur)
                last_sep = None
            if e[0] == "sep":
                if not cur:
                    continue
                last_sep = len(cur)
            cur.append(e)
            acc += w
        rows.append(cur)
        sig = tuple(len(r) for r in rows)
        if sig == self._tb_split and not force:
            return
        self._tb_split = sig
        for t in self.toolbars:
            for a in t.actions():            # not clear(): that deleted the undo / redo actions
                t.removeAction(a)
        for i, t in enumerate(self.toolbars):
            entries = rows[i] if i < len(rows) else []
            for e in entries:
                if e[0] == "sep":
                    t.addSeparator()
                elif e[0] == "act":
                    t.addAction(e[1])
                else:
                    self._add_theme_button(t)
            t.setVisible(bool(entries))
        self._decorate_toolbar()
        changed = False
        for e in self._tb_entries:                        # real widths: lay out again if the estimate was off
            if e[0] == "act":
                b = self._tool_button(e[1])
                if b is not None:
                    w = b.sizeHint().width()
                    changed |= self._tb_widths.get(id(e[1])) != w
                    self._tb_widths[id(e[1])] = w
        # exact check: a row wider than the window would hide icons behind ">>" - move the last group down
        over = max((t.sizeHint().width() - self.width() for t in self.toolbars if t.isVisible()), default=0)
        if over > 0 and len(self._tb_entries) and getattr(self, "_tb_slack", 0) < 400:
            self._tb_slack = getattr(self, "_tb_slack", 0) + over + 4
            changed = True
        if changed and not getattr(self, "_tb_again", False):
            self._tb_again = True
            try:
                self._layout_toolbar(force=True)
            finally:
                self._tb_again = False

    def _add_theme_button(self, t):
        """Theme switch: its own button at the far end of its toolbar row (far left in Arabic)."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QSizePolicy, QToolButton

        from .icons import icon
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        t.addWidget(spacer)
        self.theme_button = QToolButton()
        self.theme_button.setIcon(icon("theme"))
        self.theme_button.setIconSize(QSize(28, 28))
        self.theme_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.theme_button.setPopupMode(QToolButton.InstantPopup)
        self.theme_button.setMenu(self.m_theme)
        self.theme_button.setText(tr("theme"))
        self.theme_button.setToolTip(tr("theme"))
        t.addWidget(self.theme_button)

    def _tool_button(self, action):
        for t in getattr(self, "toolbars", []):
            if action in t.actions():
                return t.widgetForAction(action)
        return None

    def _decorate_toolbar(self):
        """Buttons are recreated when the rows change: menus / right-click menus again."""
        from PySide6.QtWidgets import QToolButton
        acts = self._acts
        b = self._tool_button(acts["export_menu"])
        if b is not None:
            b.setPopupMode(QToolButton.InstantPopup)
        b = self._tool_button(acts["run"])
        if b is not None:
            b.setObjectName("primary")              # the main action stands out (themes.py)
        for action, menu in ((acts["run"], self.m_run), (acts["save"], self.m_save),
                             (self.act_measure_tool, self.m_measure)):
            b = self._tool_button(action)
            if b is not None and not b.property("l7_menu"):
                b.setProperty("l7_menu", True)
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pos, b=b, m=menu: m.exec(b.mapToGlobal(pos)))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._layout_toolbar()

    _marker_full = False

    def toggle_marker_full(self):
        """F11: only the marker, over the whole screen (menus, icons, piece strip, status bar and open panels
        hidden); F11 or Esc brings everything back. Zoom keys keep working."""
        on = not self._marker_full
        self._marker_full = on
        self.act_marker_full.setChecked(on)
        self._act_full_exit.setEnabled(on)
        if on:
            self._full_restore = (self.isMaximized(), self.dock_strip.isVisible())
            for p in self.table_popups:
                if p.isVisible():
                    p.hide()
            self._sync_tab_actions()
            for wdg in [self.menuBar(), self.statusBar(), self.dock_strip] + list(self.toolbars):
                wdg.hide()
            self.showFullScreen()
        else:
            was_max, strip = getattr(self, "_full_restore", (True, True))
            self.menuBar().show()
            self.statusBar().show()
            self.dock_strip.setVisible(strip)
            self.showMaximized() if was_max else self.showNormal()
            self._tb_split = None
            self._layout_toolbar(force=True)
        QTimer.singleShot(0, self.view.zoom_fit)

    def eventFilter(self, obj, ev):
        """A click outside an open panel closes it (the pieces table stays open for clicks on the marker / strip,
        so selected pieces are highlighted in it); clicks in the panel's own lists, its toolbar icon or a dialog
        do not count."""
        if ev.type() == QEvent.MouseButtonPress and getattr(self, "tab_actions", None):
            gp = ev.globalPosition()
            key = (ev.timestamp(), round(gp.x(), 1), round(gp.y(), 1))      # the copies passed on keep both
            first = key != getattr(self, "_last_press", None)   # a click not used is passed on to the parents:
            self._last_press = key                               # judge it once, at the widget clicked
            open_pops = [(p, a) for p, a in zip(self.table_popups, self.tab_actions) if p.isVisible()] if first else []
            if open_pops:
                w = obj if isinstance(obj, QWidget) else None
                if w is not None and not isinstance(w.window(), QDialog):
                    for pop, action in open_pops:
                        keep = [pop, self._tool_button(action)]
                        if pop is self.pieces_popup:
                            keep += [self.view, self.strip]
                        if not any(k is not None and (w is k or k.isAncestorOf(w) or _owned_by(w, k)) for k in keep):
                            pop.hide()
        return super().eventFilter(obj, ev)

    def createPopupMenu(self):
        return None        # no toolbar/dock list on right-click: the toolbar buttons have their own menus

    def show_table_tab(self, index: int):
        """Toolbar 'Pieces' / 'Sizes': the table drops down under its icon; a second click closes it."""
        pop = self.table_popups[index]
        if pop.isVisible():
            pop.hide()
        else:
            for other in self.table_popups:
                other.hide()
            action = self.tab_actions[index]
            pop.show_below(self._tool_button(action) if hasattr(self, "toolbar") else None)
        self._sync_tab_actions()

    def _sync_tab_actions(self):
        for pop, a in zip(self.table_popups, getattr(self, "tab_actions", ())):
            a.setChecked(pop.isVisible())

    def set_theme(self, name):
        from .themes import apply_theme
        apply_theme(name)
        self.settings_store.setValue("theme", name)
        for w in self._all_windows():
            w._theme_changed()

    def _theme_changed(self):
        from .icons import icon
        for a, key in self.toolbar_items:
            a.setIcon(icon(dict((k, i) for k, i in (x for x in self.TOOLBAR if x)).get(key) or key))
        self._measure_icon()
        self.theme_button.setIcon(icon("theme"))
        for t in self.toolbars:
            t.setStyleSheet(t.styleSheet())                     # re-polish with the new palette
        for w in QApplication.instance().allWidgets():
            w.update()
        self.view.apply_theme()
        self.strip.update()

    def _retranslate_toolbar(self):
        for a, key in self.toolbar_items:
            a.setIconText(tr("tb_" + key))
            sc = a.shortcut().toString(QKeySequence.NativeText)
            a.setToolTip(a.text().replace("&", "") + (f"  ({sc})" if sc else ""))
        self._measure_icon()
        self._tb_widths = {}                     # texts changed: measure again and re-wrap the rows
        self._layout_toolbar(force=True)

    def retranslate(self):
        t = getattr(self, "pieces_table", None)
        for r in range(t.rowCount() if t is not None else 0):       # material lists: their own texts too
            b = t.cellWidget(r, 2)
            if b is not None and b.property("material") is not None:
                self._fill_material_box(b, self._material_codes(), b.property("material"))
                b.setToolTip(tr("material_tip"))
        for b in getattr(self.view, "zoom_buttons", []):
            b.setToolTip(tr(b.property("tipkey")))
        rtl = LANG["current"] == "ar"
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self._update_title()
        for a, k in self.actions_tr:
            a.setText(tr(k))
        self.undo_actions[0].setText(tr("undo"))
        self.undo_actions[1].setText(tr("redo"))
        self._retranslate_toolbar()
        self.m_theme.setTitle(tr("theme"))
        self.theme_button.setText(tr("theme"))
        self.theme_button.setToolTip(tr("theme"))
        for m, k in self.menus_tr:
            m.setTitle(tr(k))
        from .i18n import T
        for lab, k in self.form_rows:
            lab.setText(tr(k))
            tip = tr("ft_" + k) if "ft_" + k in T else ""
            lab.setToolTip(tip)
            self.form_fields[k].setToolTip(tip)
        self.pieces_popup.title.setText(tr("tab_pieces"))
        self.sizes_popup.title.setText(tr("tab_sizes"))
        self.spacing_popup.title.setText(tr("tab_spacing"))
        self.plaid_popup.title.setText(tr("tab_plaid"))
        self.plaid.retranslate()
        self._measure_icon()
        self.props_popup.title.setText(tr("fabric"))
        self.results_popup.title.setText(tr("results"))
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
        self.f_mode.setCurrentIndex(cur if cur >= 0 else 2)       # default: long search (time stays 120 s)
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
        for w in self._all_windows():
            w.retranslate()

    def _all_windows(self):
        wins = list(self.sessions.windows) if self.sessions is not None else []
        return wins if self in wins else wins + [self]

    def _mode_changed(self, i):
        self.f_time.setValue({0: 10, 1: 120, 2: 300}.get(i, 120))

    # -- file handling -------------------------------------------------------------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        self.open_many(paths)

    def open_many(self, paths):
        """One file: into this window if it is empty, else a new session; several files: one session each."""
        paths = [p for p in paths if p]
        if not paths:
            return
        if self.sessions is None:
            self.open_path(paths[0])
            return
        if len(paths) == 1 and self.project is None:
            self.open_path(paths[0])
        else:
            self.sessions.open_files(paths, prefer=self)

    def add_model_dialog(self):
        """Add further model files to this session (pieces of all models can go into one marker)."""
        from ..service import MAX_MODELS, add_model, model_tags
        if self.project is None:
            self.open_dialog()
            return
        ps, _ = QFileDialog.getOpenFileNames(self, tr("add_model"), self.settings_store.value("last_dir", ""),
                                             "Patterns / markers (*.mdl *.MDL *.scb *.SCB *.dxf *.DXF *.l7n);;All (*)")
        if not ps:
            return
        self.read_tables()
        added, problems = [], []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for path in ps:
                if len(model_tags(self.project) or [self.project.name]) >= MAX_MODELS:
                    problems.append(tr("models_max", n=MAX_MODELS))
                    break
                try:
                    other, issues = add_model(self.project, path)
                    added.append(os.path.basename(path))
                    self.issues_list.addItems([f"{os.path.basename(path)}: {i}" for i in issues[:100]])
                except Exception as exc:
                    problems.append(f"{os.path.basename(path)}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self.load_tables()
        self.refresh_markers_list(select=self.markers_list.currentRow() if self.markers_list.currentRow() >= 0 else -1)
        self.retranslate()
        if added:
            self.mark_dirty()
        msg = tr("models_added", n=len(added), t=len(model_tags(self.project)))
        if problems:
            QMessageBox.warning(self, tr("add_model"), msg + "\n\n" + "\n".join(problems))
        self.statusBar().showMessage(msg)
        self.show_table_tab(1)                 # choose the sizes of each model

    def batch_dialog(self):
        from .batch_dialog import BatchDialog
        dlg = getattr(self, "_batch_dlg", None)
        try:
            if dlg is not None and dlg.isVisible():   # one list window per session: bring it to the front
                dlg.raise_()
                dlg.activateWindow()
                return
        except RuntimeError:                          # already deleted
            pass
        dlg = BatchDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._batch_dlg = dlg
        dlg.show()

    def new_session(self):
        if self.sessions is not None:
            self.sessions.new_window()

    def open_dialog(self):
        ps, _ = QFileDialog.getOpenFileNames(self, tr("open"), self.settings_store.value("last_dir", ""),
                                             "Patterns / markers (*.mdl *.MDL *.scb *.SCB *.dxf *.DXF *.l7n);;All (*)")
        self.open_many(ps)

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
        self.scb_template_path = path if path.lower().endswith(".scb") else None
        self.undo.clear()
        self.load_tables()
        if proj.markers:
            self.form_from_fabric(proj.markers[0].fabric)
        self.refresh_markers_list(select=0 if proj.markers else -1)
        msg = f"{os.path.basename(path)}: {len(proj.pieces)} pieces"
        if proj.sources and proj.sources[0].internal_model_name:
            msg += f" | internal model name: {proj.sources[0].internal_model_name}"
        if issues:
            msg += f" | {len(issues)} read issues"
            self.issues_list.addItems(issues[:200])
        self.statusBar().showMessage(msg)
        self.retranslate()
        self.mark_dirty(False)                 # freshly opened = nothing to save yet
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

    # -- plaid / stripe matching ------------------------------------------------------------
    def _redraw_marker(self):
        if self.marker is not None:
            self.view.show_marker(self.project, self.marker, self.view.bad)
            self.after_edit()

    def _plaid_fabric_changed(self):
        """The repeat applies to the marker on screen at once (lines, check) and to the next nesting run."""
        if self.marker is not None:
            for k, v in self.plaid.values().items():
                setattr(self.marker.fabric, k, v)
            self.mark_dirty()
            self._redraw_marker()

    def _plaid_rules_changed(self):
        self.mark_dirty()
        self._redraw_marker()

    def _plaid_pick(self, on):
        if on:
            self.set_measure(None)
            self.plaid_popup.hide()
            self.statusBar().showMessage(tr("plaid_pick_hint"))
        else:
            self.statusBar().clearMessage()
        self.view.set_pick_match(on)

    def _match_picked(self, uid, kind, index):
        pc = self.project.piece(uid)
        old = pc.match or {}
        pc.match = {"kind": kind, "index": index, "x": old.get("x", True), "y": old.get("y", True),
                    "dx": old.get("dx", 0.0), "dy": old.get("dy", 0.0)}
        self.plaid.fill()
        self.statusBar().showMessage(tr("plaid_picked", p=pc.name, a=tr("plaid_notch" if kind == "notch"
                                                                        else "plaid_corner", n=index + 1)))
        self._plaid_rules_changed()

    def load_tables(self):
        self._loading_tables = True
        try:
            self._load_tables()
        finally:
            self._loading_tables = False
        self._synced_order = self._order_signature() if self.project is not None else None

    def _table_edited(self, *_):
        if not getattr(self, "_loading_tables", False):
            self.mark_dirty()
            if self.project is not None:          # the strip follows the chosen sizes / quantities at once
                self.read_tables()
                self._sync_marker()
                self._refresh_strip()

    def _order_signature(self):
        co = self.project.cut_order
        return (tuple(sorted(co.size_quantities.items())), tuple(sorted(co.piece_counts.items())))

    def _sync_marker(self):
        """The marker follows the order at once: copies no longer ordered leave it, new ones wait unplaced. Only
        a change of the order itself (sizes, quantities, parts used, copies) does this - not a grain angle or a
        material; it is one undo step, and copies ordered again come back where they were."""
        from ..service import sync_marker_to_order
        if self.marker is None or (self.worker is not None and self.worker.isRunning()):
            return
        sig = self._order_signature()
        if sig == getattr(self, "_synced_order", None):
            return
        self._synced_order = sig
        spare = self._sync_spare.setdefault(id(self.marker), [])
        old = list(self.marker.placements)
        removed, added = sync_marker_to_order(self.project, self.marker, spare)
        if removed or added:
            self.undo.push(OrderSyncCommand(self, self.marker, old, list(self.marker.placements)))
            self.statusBar().showMessage(tr("order_synced", r=removed, a=added))

    def _load_tables(self):
        p = self.project
        self.plaid.set_project(p)
        t = self.pieces_table
        t.setRowCount(0)
        co = p.cut_order
        all_mats = sorted({pc.material for pc in p.pieces if pc.material} | {"O", "F"})
        model_order = {m: i for i, m in enumerate(dict.fromkeys(q.model for q in p.pieces))}
        for pc in sorted(p.pieces, key=lambda q: (model_order[q.model], not q.production, q.number or 0)):
            r = t.rowCount()
            t.insertRow(r)
            use = QTableWidgetItem()
            n, m = co.piece_counts.get(pc.uid, (0, 0))
            use.setCheckState(Qt.Checked if (n or m) else Qt.Unchecked)
            use.setData(Qt.UserRole, pc.uid)
            t.setItem(r, 0, use)
            t.setItem(r, 1, QTableWidgetItem(f"{pc.number or ''} {pc.name}" + (f"   [{pc.model}]" if pc.model else "")))
            t.setItem(r, 2, QTableWidgetItem(""))
            mat = QComboBox()                       # material of the part: a list (click opens it) + "New material…"
            self._fill_material_box(mat, all_mats, pc.material)
            mat.setToolTip(tr("material_tip"))
            mat.activated.connect(lambda _i, b=mat: self._material_chosen(b))
            t.setCellWidget(r, 2, mat)
            t.setItem(r, 3, QTableWidgetItem(str(len(pc.sizes))))
            for col, val in ((4, n or pc.default_count), (5, m if (n or m) else pc.default_mirrored)):
                s = QSpinBox()
                s.setRange(0, 20)
                s.setValue(val)
                s.valueChanged.connect(self._table_edited)
                t.setCellWidget(r, col, s)
            g = QDoubleSpinBox()
            g.setRange(-1, 179.99)
            g.setSpecialValueText(tr("grain_unknown"))
            g.setValue(pc.grain_angle if pc.grain_angle is not None else -1)
            g.valueChanged.connect(self._table_edited)
            t.setCellWidget(r, 6, g)
            for c in (1, 2, 3):
                t.item(r, c).setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._row_select.attach()
        st = self.sizes_table
        st.setRowCount(0)
        st.clearSpans()
        from ..service import MODEL_SEP, model_tags
        tags = model_tags(p)
        last_tag = None
        for s in p.size_names:
            tag = s.split(MODEL_SEP, 1)[0] if tags and MODEL_SEP in s else None
            if tags and tag != last_tag:
                # several models: a separator row with the model's name before its sizes
                last_tag = tag
                r = st.rowCount()
                st.insertRow(r)
                head = QTableWidgetItem(f"{tags.index(tag) + 1} = {tag}" if tag in tags else (tag or ""))
                head.setFlags(Qt.ItemIsEnabled)
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                head.setBackground(self.palette().alternateBase())
                st.setItem(r, 0, head)
                st.setSpan(r, 0, 1, 2)
            r = st.rowCount()
            st.insertRow(r)
            it = QTableWidgetItem(s.split(MODEL_SEP, 1)[1] if tag else s)   # size without the model name
            it.setData(Qt.UserRole, s)
            it.setFlags(Qt.ItemIsEnabled)
            st.setItem(r, 0, it)
            sp = QSpinBox()
            sp.setRange(0, 999)
            sp.setValue(co.size_quantities.get(s, 0))
            sp.valueChanged.connect(self._table_edited)
            st.setCellWidget(r, 1, sp)
        self._refresh_material_groups(co.material)

    # -- material of the parts (pieces table) ------------------------------------------------------
    NEW_MATERIAL = "\x00new"

    def _fill_material_box(self, box, codes, current):
        box.blockSignals(True)
        box.clear()
        box.addItem(tr("mat_none"), "")
        for c in codes:
            box.addItem(c, c)
        box.addItem(tr("mat_new"), self.NEW_MATERIAL)
        box.setCurrentIndex(max(0, box.findData(current or "")))
        box.setProperty("material", current or "")
        box.blockSignals(False)

    def _material_codes(self):
        t = self.pieces_table
        codes = {t.cellWidget(r, 2).property("material") for r in range(t.rowCount()) if t.cellWidget(r, 2)}
        return sorted({c for c in codes if c} | {"O", "F"})

    def _ask_material(self):
        from PySide6.QtWidgets import QInputDialog
        code, ok = QInputDialog.getText(self, tr("mat_new_title"), tr("mat_new_prompt"))
        code = code.strip().upper() if ok else ""
        return code[:8] or None

    def _set_materials(self, rows, code):
        """Give these rows of the pieces table the material code ('' = none); every list knows a new code."""
        t = self.pieces_table
        codes = sorted(set(self._material_codes()) | ({code} if code else set()))
        for r in range(t.rowCount()):
            b = t.cellWidget(r, 2)
            if b is not None:
                self._fill_material_box(b, codes, code if r in rows else b.property("material"))
        self._refresh_material_groups()
        self._table_edited()

    def _material_chosen(self, box):
        code = box.currentData()
        if code == self.NEW_MATERIAL:
            code = self._ask_material()
            if code is None:                              # cancelled: back to the material it had
                box.setCurrentIndex(max(0, box.findData(box.property("material") or "")))
                return
        self._set_materials({int(box.property("row"))} if box.property("row") is not None else
                            {r for r in range(self.pieces_table.rowCount()) if self.pieces_table.cellWidget(r, 2) is box},
                            code)

    def _pieces_menu(self, pos):
        """Right-click in the pieces table: material for all selected parts at once."""
        from PySide6.QtWidgets import QMenu
        t = self.pieces_table
        rows = {i.row() for i in t.selectedIndexes()}
        r0 = t.rowAt(pos.y())
        if r0 >= 0 and r0 not in rows:
            rows = {r0}
            t.selectRow(r0)
        if not rows:
            return
        m = QMenu(self)
        sub = m.addMenu(tr("mat_set_selected", n=len(rows)))
        for c in self._material_codes():
            sub.addAction(c, lambda c=c: self._set_materials(rows, c))
        sub.addAction(tr("mat_none"), lambda: self._set_materials(rows, ""))
        sub.addSeparator()
        sub.addAction(tr("mat_new"), lambda: (lambda c: c and self._set_materials(rows, c))(self._ask_material()))
        m.exec(t.viewport().mapToGlobal(pos))

    def _refresh_material_groups(self, select=None):
        """Material to nest: the material codes used by the pieces of the file (as assigned in the pieces table),
        with the GRAFIS material name when the file has one (SCB: MATERIAL<code>) and the number of pieces."""
        counts: dict[str, int] = {}
        for r in range(self.pieces_table.rowCount()):
            w = self.pieces_table.cellWidget(r, 2)
            use = self.pieces_table.item(r, 0)
            code = w.property("material") if w is not None else None
            if code and use is not None and use.checkState() == Qt.Checked:
                counts[code] = counts.get(code, 0) + 1
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
                pc.material = mat_w.property("material") or None
            n = self.pieces_table.cellWidget(r, 4).value()
            m = self.pieces_table.cellWidget(r, 5).value()
            co.piece_counts[uid] = (n, m) if use else (0, 0)
            g = self.pieces_table.cellWidget(r, 6).value()
            pc.grain_angle = None if g < 0 else g
        co.size_quantities = {self.sizes_table.item(r, 0).data(Qt.UserRole): self.sizes_table.cellWidget(r, 1).value()
                              for r in range(self.sizes_table.rowCount())
                              if self.sizes_table.cellWidget(r, 1) is not None}     # model separator rows skipped
        mat = self.f_material.currentData()
        co.material = None if mat in ("*", "", None) else mat

    def form_from_fabric(self, f: FabricSettings):
        """Show a marker's fabric settings in the form (so 'Nest' continues from what is on screen)."""
        lay = {LayType.OPEN: 0, LayType.FACE_TO_FACE: 1, LayType.FOLDED: 2}.get(f.lay_type, 0)
        for w, v in ((self.f_width, f.width), (self.f_ml, f.margin_left), (self.f_mr, f.margin_right),
                     (self.f_ms, f.margin_start), (self.f_me, f.margin_end), (self.f_sp, f.spacing),
                     (self.f_bx, f.buffer_x), (self.f_by, f.buffer_y), (self.f_shx, f.shrink_x),
                     (self.f_shy, f.shrink_y), (self.f_maxlen, f.max_length or 0.0)):
            w.setValue(v)
        self.f_lay.setCurrentIndex(lay)
        if hasattr(self, "plaid"):
            self.plaid.set_values(f)

    def fabric_from_form(self) -> FabricSettings:
        lay = [LayType.OPEN, LayType.FACE_TO_FACE, LayType.FOLDED][max(0, self.f_lay.currentIndex())]
        return FabricSettings(width=self.f_width.value(), margin_left=self.f_ml.value(), margin_right=self.f_mr.value(),
                              margin_start=self.f_ms.value(), margin_end=self.f_me.value(), spacing=self.f_sp.value(),
                              buffer_x=self.f_bx.value(), buffer_y=self.f_by.value(),
                              shrink_x=self.f_shx.value(), shrink_y=self.f_shy.value(), **self.plaid.values(),
                              lay_type=lay, max_length=self.f_maxlen.value() or None)

    def nest_settings_from_form(self) -> NestSettings:
        return NestSettings(mode=["fast", "balanced", "long"][max(0, self.f_mode.currentIndex())],
                            engine="auto" if self.f_engine.currentIndex() <= 0 else "builtin",
                            time_limit=float(self.f_time.value()), seed=self.f_seed.value(),
                            allow_rotation_180=self.f_rot180.isChecked(), allow_rotation_90=self.f_rot90.isChecked(),
                            curve_tolerance=self.f_tol.value(), best_of=self.f_best.value())

    def mark_dirty(self, on: bool = True):
        try:
            if self.project is None:
                on = False
            if on != self.dirty:
                self.dirty = on
                self._update_title()
        except RuntimeError:          # window already being destroyed (undo stack signals on shutdown)
            pass

    def _update_title(self):
        self.setWindowTitle(f"{tr('app_title')} {__version__}" +
                            (f" — {self.project.name}{' *' if self.dirty else ''}" if self.project else ""))

    def _scb_possible(self):
        """GRAFIS SCB template for this session (single model with a marker), else None."""
        from ..service import scb_template
        if self.project is None or self.marker is None or any(p.model for p in self.project.pieces):
            return None
        if any(pl.sx != 1.0 or pl.sy != 1.0 for pl in self.marker.placements):
            return None                        # shrinkage is not written to SCB (see formats.grafis.writer)
        return getattr(self, "scb_template_path", None) or scb_template(self.project)

    def save(self) -> bool:
        if not self.project:
            return True
        if not self.project_path:
            return self.save_as()
        self.read_tables()
        try:
            if self.project_path.lower().endswith(".scb"):
                import shutil
                from ..formats.grafis.writer import write_scb
                template = self._scb_possible()
                if template is None:
                    QMessageBox.warning(self, tr("save"), tr("scb_not_possible"))
                    return self.save_as()
                others = [m for m in self.project.markers if m is not self.marker and m.origin != "original"]
                if others and QMessageBox.question(self, tr("save"), tr("scb_one_marker", n=len(others)),
                                                   QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                    return False
                tmp_t = None
                if os.path.abspath(template) == os.path.abspath(self.project_path):
                    bak = self.project_path + ".bak"
                    if not os.path.exists(bak):            # keep GRAFIS' original once before overwriting it
                        shutil.copy2(self.project_path, bak)
                    import tempfile
                    fd, tmp_t = tempfile.mkstemp(suffix=".scb")
                    os.close(fd)
                    shutil.copy2(template, tmp_t)
                    template = tmp_t
                try:
                    write_scb(template, self.project, self.marker, self.project_path)
                finally:
                    if tmp_t:
                        os.remove(tmp_t)
            else:
                from ..project_storage.store import save_project
                save_project(self.project, self.project_path)
        except Exception as e:
            QMessageBox.critical(self, tr("save"), str(e))
            return False
        self.statusBar().showMessage(tr("saved", p=self.project_path))
        self.mark_dirty(False)
        return True

    def _save_mdl(self, path):
        """GRAFIS MDL: the model file this session was read from, with the parts' material / production /
        copies from the pieces table (geometry copied unchanged). The original is kept once as .bak."""
        import shutil
        import tempfile

        from ..formats.grafis.mdl_writer import write_mdl
        from ..service import mdl_template
        template = mdl_template(self.project)
        if template is None:
            raise ValueError(tr("mdl_not_possible"))
        from ..formats.grafis.container import sha256_bytes
        src = next(x for x in self.project.sources if x.kind == "mdl" and os.path.abspath(x.path) ==
                   os.path.abspath(template))
        with open(template, "rb") as fh:
            if src.sha256 and sha256_bytes(fh.read()) != src.sha256:
                # changed in GRAFIS after LEVEL7 opened it: writing would bring back this session's older
                # production / copies / materials over GRAFIS' newer ones
                raise ValueError(tr("mdl_changed_on_disk"))
        tmp_t = None
        if os.path.abspath(template) == os.path.abspath(path):
            if not os.path.exists(path + ".bak"):
                shutil.copy2(path, path + ".bak")
            fd, tmp_t = tempfile.mkstemp(suffix=".mdl")
            os.close(fd)
            shutil.copy2(template, tmp_t)
            template = tmp_t
        try:
            write_mdl(template, self.project, path)
        finally:
            if tmp_t:
                os.remove(tmp_t)
        if os.path.abspath(src.path) == os.path.abspath(path):     # our own write: the session knows this file
            with open(path, "rb") as fh:
                src.sha256 = sha256_bytes(fh.read())

    def save_mdl_as(self):
        """File > Save as GRAFIS MDL…: the model with the parts' material / production / copies."""
        from ..service import mdl_template
        if not self.project:
            return
        template = mdl_template(self.project)
        if template is None:
            QMessageBox.warning(self, tr("save_mdl"), tr("mdl_not_possible"))
            return
        self.read_tables()
        p, _ = QFileDialog.getSaveFileName(self, tr("save_mdl"), template, "GRAFIS MDL (*.mdl)")
        if not p:
            return
        if not p.lower().endswith(".mdl"):
            p += ".mdl"
        try:
            self._save_mdl(p)
        except Exception as e:
            QMessageBox.critical(self, tr("save_mdl"), str(e))
            return
        self.statusBar().showMessage(tr("mdl_saved", p=p))

    def save_as(self) -> bool:
        """Default: GRAFIS SCB when the session allows it (like GRAFIS), else the LEVEL7 project format."""
        if not self.project:
            return True
        from ..service import mdl_template
        template = self._scb_possible()
        f_scb, f_l7n, f_mdl = "GRAFIS SCB (*.scb)", "LEVEL7 project (*.l7n)", "GRAFIS MDL (*.mdl)"
        filters = f"{f_scb};;{f_l7n}" if template else f_l7n
        if mdl_template(self.project):
            filters += f";;{f_mdl}"
        start_dir = os.path.dirname(template) if template else self.settings_store.value("last_dir", "")
        name = self.project.name + (".scb" if template else ".l7n")
        p, chosen = QFileDialog.getSaveFileName(self, tr("save_as"), os.path.join(start_dir, name), filters,
                                                f_scb if template else f_l7n)
        if not p:
            return False
        ext = ".scb" if chosen == f_scb else ".mdl" if chosen == f_mdl else ".l7n"
        if not p.lower().endswith(ext):
            p = os.path.splitext(p)[0] + ext
        if ext == ".mdl":
            # the model file only (materials / copies): not the session file - markers are not in it, so the
            # session stays "unsaved" and keeps its own path
            self.read_tables()
            try:
                self._save_mdl(p)
            except Exception as e:
                QMessageBox.critical(self, tr("save_mdl"), str(e))
                return False
            self.statusBar().showMessage(tr("mdl_saved", p=p))
            return False
        if ext == ".scb":
            self.scb_template_path = template          # keep the GRAFIS template of this session
        self.project_path = p
        return self.save()

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
        self.form_from_fabric(self.marker.fabric)
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
        self.issues_list.addItems([i.message for i in v.issues][:500] or [self.issues_summary(v)])
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

    def _marker_selection_changed(self):
        try:
            uids = {pl.piece_uid for pl in self.view.selected_placements()}
        except RuntimeError:                 # window being destroyed
            return
        self._highlight_pieces(uids)

    def _highlight_pieces(self, uids):
        """Pieces selected on the marker / clicked in the strip: their rows are highlighted in the pieces table."""
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        try:
            t = self.pieces_table
            t.rowCount()
        except RuntimeError:                 # window being destroyed
            return
        sel = QItemSelection()
        first = None
        for r in range(t.rowCount()):
            it = t.item(r, 0)
            if it is not None and it.data(Qt.UserRole) in uids:
                sel.select(t.model().index(r, 0), t.model().index(r, t.columnCount() - 1))
                first = r if first is None else first
        t.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect)
        if first is not None:
            t.scrollToItem(t.item(first, 0))

    def _toggle_strip_row(self, size, bundle):
        """Strip check box: include / exclude this size+bundle in the next nesting run."""
        if self.project is None:
            return
        co = self.project.cut_order
        ex = {(s, int(b)) for s, b in co.excluded}
        if bundle:
            ex ^= {(size, bundle)}
        else:                                    # the whole size: every bundle of the order and of the marker
            n = max([co.size_quantities.get(size, 0)] +
                    [pl.bundle for pl in (self.marker.placements if self.marker else []) if pl.size == size])
            rows = {(size, b) for b in range(1, n + 1)}
            ex = (ex - rows) if rows <= ex else (ex | rows)
        co.excluded = sorted(ex)
        self.mark_dirty()
        self._refresh_strip()
        from .marker_view import bundle_letter
        key = "strip_row_off" if (size, bundle or 1) in ex else "strip_row_on"
        self.statusBar().showMessage(tr(key, r=f"{size}/{bundle_letter(bundle)}" if bundle else size))

    def _refresh_strip(self):
        self.strip.set_data(self.project, self.marker)
        self._strip_height()

    def _strip_height(self):
        from .piece_strip import ROW_H, TOP
        rows = self.strip.lines()                 # size rows are laid side by side, wrapped into lines
        hbar = self.strip.sizeHint().width() > self.strip_area.width()
        extra = 6 + (self.strip_area.horizontalScrollBar().sizeHint().height() if hbar else 0)   # scroll bar
        # up to 5 model lines in view (a 4th model was hidden below 3 lines); more scroll with the mouse wheel
        self.strip_area.setFixedHeight(TOP + min(rows, 5) * ROW_H + extra)

    def update_results(self, v=None):
        if not self.marker or not self.project:
            self.results_text.setPlainText("")
            self._refresh_strip()
            return
        self._refresh_strip()
        s = self.marker.stats or marker_stats(self.project, self.marker)
        lines = [tr("r_width", w=s["width_mm"], u=s["usable_width_mm"]),
                 tr("r_length", v=s["length_mm"]), tr("r_placed", p=s["placed"], u=s["unplaced"]),
                 tr("r_area", v=s["pieces_area_m2"]),
                 tr("r_eff_total", v=s["efficiency_total_width_pct"]),
                 tr("r_eff_usable", v=s["efficiency_usable_width_pct"]),
                 tr("r_waste", v=s["waste_pct"]),
                 tr("r_consumption", m=s["consumption_m"], y=s["consumption_yd"]),
                 tr("r_per_garment", v=s.get("length_per_garment_m", 0), n=s.get("garments", 0)),
                 tr("r_by_size") + ", ".join(f"{k}: {n}" for k, n in sorted(s["by_size"].items()))]
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
            lines.append(tr("r_time", t=self.marker.compute_time, s=self.marker.seed))
        if v is not None:
            lines.append(f"{tr('issues')}: {tr('valid') if v.ok else tr('invalid')}")
        orig = next((m for m in self.project.markers if m.origin == "original"), None)
        if orig is not None and orig is not self.marker:
            so = marker_stats(self.project, orig)
            lines += ["", tr("compare"),
                      tr("r_cmp_length", a=so["length_mm"], b=s["length_mm"], d=s["length_mm"] - so["length_mm"]),
                      tr("r_cmp_width", a=so["width_mm"], b=s["width_mm"]),
                      tr("r_cmp_eff", a=so["efficiency_total_width_pct"], b=s["efficiency_total_width_pct"]),
                      tr("r_cmp_pieces", a=so["placed"], b=s["placed"])]
        if self.project.sbinfo:
            lines += ["", "GRAFIS: " + ", ".join(f"{k}={self.project.sbinfo[k]}" for k in
                                                 ("WIDTH", "LENGTH", "EFFCNCY", "USDAREA", "PCSTOTAL", "MODEL")
                                                 if k in self.project.sbinfo)]
        self.results_text.setPlainText("\n".join(lines))

    # -- manual editing --------------------------------------------------------------------
    def on_moved(self, moves):
        if not self.marker or self._busy():
            if self._busy():
                self.view.refresh()
            return
        changes = []
        from dataclasses import replace

        from .. import matching
        for pl, dx, dy in moves:
            if pl.pinned:
                continue
            old = PlacementStateCommand.state(pl)
            pc = self.project.piece(pl.piece_uid)
            if matching.active(pc, self.marker.fabric):       # plaid: snap the match point onto its line
                sx, sy = matching.snap(pc, replace(pl, x=pl.x + dx, y=pl.y + dy), self.marker.fabric)
                dx, dy = dx + sx, dy + sy
            new = (pl.x + dx, pl.y + dy) + old[2:]
            if self._off_fabric(pc, replace(pl, x=pl.x + dx, y=pl.y + dy)):
                new = old[:5] + (False, TAKEN_OUT)        # dropped off the fabric: back to the strip
            changes.append((pl, old, new))
        if changes:
            self.marker.origin = "manual" if self.marker.origin != "original" else "original"
            self.undo.push(PlacementStateCommand(self, changes, "move"))
        else:
            self.view.refresh()

    def place_from_strip(self, size, uid, mirrored, x, y):
        """A piece dragged from the strip onto the marker: one copy still to place goes there (its centre at the
        drop point); a copy taken out keeps its turn, a new one gets the first turn its grain allows. Undo-able;
        overlaps show in red like any manual move."""
        if not self.marker or self._busy():
            return
        from dataclasses import replace

        from ..geometry import bbox
        from ..service import allowed_rotation_map
        ex = {(s, int(b)) for s, b in self.project.cut_order.excluded}
        cands = [pl for pl in self.marker.placements if not pl.placed and pl.piece_uid == uid and pl.size == size
                 and (size, pl.bundle) not in ex]
        if not cands:
            return
        cands.sort(key=lambda pl: (pl.mirrored != mirrored, pl.reason != TAKEN_OUT, pl.bundle))
        pl = cands[0]
        piece = self.project.piece(uid)
        rot = pl.rotation
        if pl.reason != TAKEN_OUT:
            rots = allowed_rotation_map(self.project, self.nest_settings_from_form()).get((uid, pl.mirrored)) or [0.0]
            rot = rots[0]
        x0, y0, x1, y1 = bbox(placement_points(piece.sizes[size].cut, replace(pl, x=0.0, y=0.0, rotation=rot)))
        old = PlacementStateCommand.state(pl)
        new = (x - (x0 + x1) / 2, y - (y0 + y1) / 2, rot, pl.mirrored, False, True, None)
        if self.marker.origin != "original":
            self.marker.origin = "manual"
        self.undo.push(PlacementStateCommand(self, [(pl, old, new)], "place"))
        item = self.view.items_by_uid.get(pl.uid)
        if item is not None:
            self.view.scene().clearSelection()
            item.setSelected(True)

    def _off_fabric(self, piece, pl) -> bool:
        """The whole piece lies outside the fabric (above / below it or before its start)."""
        from ..geometry import bbox
        x0, y0, x1, y1 = bbox(placement_points(piece.sizes[pl.size].cut, pl))
        return y0 >= self.marker.fabric.width or y1 <= 0 or x1 <= 0

    def take_out_selected(self):
        """Delete: the selected pieces leave the marker (counted again in the strip); undo brings them back."""
        if not self.marker or self._busy():
            return
        changes = [(pl, PlacementStateCommand.state(pl), PlacementStateCommand.state(pl)[:5] + (False, TAKEN_OUT))
                   for pl in self.view.selected_placements() if pl.placed and not pl.pinned]
        if changes:
            self.undo.push(PlacementStateCommand(self, changes, "take out"))

    def rotate_selected(self):
        if not self.marker or self._busy():
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
            changes.append((pl, PlacementStateCommand.state(pl),
                            (nx, ny, tmp.rotation, pl.mirrored, pl.pinned, pl.placed, pl.reason)))
        if changes:
            self.undo.push(PlacementStateCommand(self, changes, "rotate 180"))

    def pin_selected(self):
        if not self.marker or self._busy():
            return
        changes = [(pl, PlacementStateCommand.state(pl),
                    PlacementStateCommand.state(pl)[:4] + (not pl.pinned,) + PlacementStateCommand.state(pl)[5:])
                   for pl in self.view.selected_placements()]
        if changes:
            self.undo.push(PlacementStateCommand(self, changes, "pin"))

    def set_measure(self, kind):
        """kind: 'line' (distance), 'curve' (along a piece edge) or None (off). Keeps menu, toolbar and view in step."""
        if kind:
            self.measure_kind = kind
            self.settings_store.setValue("measure_kind", kind)
        self.act_measure.setChecked(kind == "line")
        self.act_measure_curve.setChecked(kind == "curve")
        self.act_measure_tool.setChecked(kind is not None)
        self._measure_icon()
        self.view.set_measure_mode(kind is not None, kind or "line")
        if kind:
            self.statusBar().showMessage(tr("measure_curve_hint" if kind == "curve" else "measure_hint"))

    def _measure_icon(self):
        from .icons import icon
        if hasattr(self, "act_measure_tool"):
            curve = getattr(self, "measure_kind", "line") == "curve"
            self.act_measure_tool.setIcon(icon("measure_curve" if curve else "measure"))
            self.act_measure_tool.setToolTip(tr("measure_curve" if curve else "measure") + "\n" + tr("measure_tool_tip"))

    def toggle_measure_tool(self, on):
        self.set_measure(self.measure_kind if on else None)

    def toggle_measure_curve(self, on):
        self.set_measure("curve" if on else None)

    def toggle_measure(self, on):
        self.set_measure("line" if on else None)

    def display_options(self):
        import json

        from .display_options import DisplayOptionsDialog
        dlg = DisplayOptionsDialog(self.view.options, self)
        if dlg.exec() == QDialog.Accepted:
            opts = dlg.result_options()
            self.settings_store.setValue("display_options", json.dumps(opts))
            self.view.set_options(**opts)
            self.update_status_line()

    def update_status_line(self):
        """GRAFIS-style status: L, E, U/B, Wi (metres, or millimetres if chosen)."""
        if not self.marker or "length_mm" not in (self.marker.stats or {}):
            self.grafis_status.clear()
            return
        s = self.marker.stats
        self._show_status(s["length_mm"], s["efficiency_total_width_pct"],
                          s.get("length_per_garment_m", 0) * 1000, s["width_mm"])

    def _fmt_len(self, v: float) -> str:
        """Lengths in the status bar: one unit for everything (metres, or millimetres in the display options)."""
        return f"{v:.1f} mm" if self.view.options.get("status_mm") else f"{v / 1000:.2f} m"

    def _show_status(self, length, eff, ub, width):
        f = self._fmt_len
        self.grafis_status.set_values({"L": f(length), "E": f"{eff:.1f} %", "U/B": f(ub), "Wi": f(width)})

    def _live_length(self):
        """While a piece is dragged: L / E / U/B from the current piece positions (no validation)."""
        if not self.marker or not self.marker.stats:
            return
        items = list(self.view.items_by_uid.values())
        if not items:
            return
        f = self.marker.fabric
        right = max(it.mapToScene(it.path().boundingRect()).boundingRect().right() for it in items)
        length = right + f.margin_end
        s = self.marker.stats
        area = s.get("pieces_area_m2", 0.0) * 1e6
        eff = 100.0 * area / (f.width * length) if f.width and length > 0 else 0.0
        garments = s.get("garments") or 0
        self._show_status(length, eff, (length / garments) if garments else 0.0, f.width)

    # -- nesting ---------------------------------------------------------------------------
    def run_nesting(self, inside_only=None, best_of=None):
        """inside_only: True = re-nest only the pieces still in the marker; None = ask when pieces were taken out."""
        if not self.project or (self.worker and self.worker.isRunning()):
            return
        self.read_tables()
        out = [pl for pl in (self.marker.placements if self.marker else []) if not pl.placed and pl.reason == TAKEN_OUT]
        if inside_only is None and out:
            r = QMessageBox.question(self, tr("run"), tr("renest_ask", n=len(out)),
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if r == QMessageBox.Cancel:
                return
            inside_only = r == QMessageBox.Yes
        if inside_only:
            return self._renest_inside(best_of)
        if not self._check_cut_order():
            return
        if not self._ensure_geometry():
            return
        fabric = self.fabric_from_form()
        st = self.nest_settings_from_form()
        if best_of:
            st.best_of = best_of
        self.project.nest_settings = st
        pinned = [copy.copy(pl) for pl in (self.marker.placements if self.marker else [])
                  if pl.pinned and pl.placed and self.marker.origin != "original"]
        self._engine_note = self._builtin_reason(fabric, st, bool(pinned))
        self.worker = NestWorker(self.project, fabric, st, self.project.cut_order, pinned)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(lambda e: (_nest_log("failed: " + e.splitlines()[0] if e else "failed"),
                                              self._nest_ui(False), QMessageBox.critical(self, tr("run"), e)))
        self.worker.waiting.connect(self._nest_waiting)
        self.worker.cancelled.connect(lambda: (self._nest_ui(False), self.statusBar().showMessage(tr("nest_cancelled"))))
        self._nest_ui(True)
        _nest_log(f"start: time {st.time_limit:g} s x{max(1, st.best_of or 1)}, engine {st.engine}, "
                  f"workers {NEST_SLOTS.workers()}, note {getattr(self, '_engine_note', '')!r}")
        self.worker.start()

    def _stop_watch(self, worker):
        """Still running 20 s after Stop: write where every thread is (hang.log) - to find the cause."""
        if worker is not None and worker.isRunning():
            _nest_log("still running 20 s after Stop - thread stacks follow in hang.log")
            try:
                import faulthandler

                from .app import log_dir
                with open(os.path.join(log_dir(), "hang.log"), "a", encoding="utf-8") as fh:
                    fh.write(f"\n=== still nesting 20 s after Stop {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                    fh.flush()
                    faulthandler.dump_traceback(file=fh, all_threads=True)
            except Exception:
                pass
            self.statusBar().showMessage(tr("nest_stop_slow"))

    def _builtin_reason(self, fabric, st, pinned) -> str:
        """Why this run uses only the built-in engine (slow on big jobs) instead of sparrow - shown while it runs."""
        import os as _os

        from .. import matching
        from ..nesting import sparrow
        engine = _os.environ.get("LEVEL7_ENGINE", st.engine or "auto")
        if engine not in ("auto", "sparrow"):
            return tr("eng_why_chosen")
        if not sparrow.available():
            return tr("eng_why_missing")
        if pinned:
            return tr("eng_why_pinned")
        if fabric.max_length:
            return tr("eng_why_maxlen")
        co = self.project.cut_order
        if any(matching.active(p, fabric) for p in self.project.pieces if any(co.piece_counts.get(p.uid, (0, 0)))):
            return tr("eng_why_plaid")
        return ""

    def renest_inside(self):
        if self.project and self.marker and not (self.worker and self.worker.isRunning()):
            self.read_tables()
            self._renest_inside()

    def _renest_inside(self, best_of=None):
        """Re-nest the pieces in the current marker only; pieces taken out stay in the strip (not placed)."""
        inside = [copy.copy(pl) for pl in self.marker.placements if pl.placed]
        keep_out = [copy.copy(pl) for pl in self.marker.placements if not pl.placed]
        if not inside:
            QMessageBox.information(self, tr("run"), tr("renest_empty"))
            return
        fabric = self.fabric_from_form()
        st = self.nest_settings_from_form()
        if best_of:
            st.best_of = best_of
        self.project.nest_settings = st
        self._engine_note = self._builtin_reason(fabric, st, any(pl.pinned for pl in inside))
        self.worker = NestWorker(self.project, fabric, st, self.project.cut_order, [], placements=inside,
                                 keep_out=keep_out)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(lambda e: (_nest_log("failed: " + e.splitlines()[0] if e else "failed"),
                                              self._nest_ui(False), QMessageBox.critical(self, tr("run"), e)))
        self.worker.waiting.connect(self._nest_waiting)
        self.worker.cancelled.connect(lambda: (self._nest_ui(False), self.statusBar().showMessage(tr("nest_cancelled"))))
        self._nest_ui(True)
        _nest_log(f"start: time {st.time_limit:g} s x{max(1, st.best_of or 1)}, engine {st.engine}, "
                  f"workers {NEST_SLOTS.workers()}, note {getattr(self, '_engine_note', '')!r}")
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
            self.show_table_tab(1 if not sizes else 0)
        return False

    def _ensure_geometry(self) -> bool:
        """Selected sizes without geometry (an SCB holds only some sizes): offer to load them from the MDL."""
        from ..service import supplement_from_model
        co = self.project.cut_order
        sizes = [s for s, q in co.size_quantities.items() if q > 0]
        used = {u for u, (n, m) in co.piece_counts.items() if n + m > 0}
        def wanted(p, s):          # several models in one session: a size belongs to its own model only
            return p.uid in used and (not p.model or s.startswith(p.model + ":"))
        miss = {s: [p.name for p in self.project.pieces if wanted(p, s) and s not in p.sizes] for s in sizes}
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
            left = {s for s in sizes for p in self.project.pieces if wanted(p, s) and s not in p.sizes}
            if left:
                QMessageBox.warning(self, tr("run"), tr("missing_sizes_left", s=", ".join(sorted(left))))
        return True

    def _nest_ui(self, running):
        self._stopping = False
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.progress_bar.setVisible(running)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        if not hasattr(self, "_nest_timer"):
            self._nest_timer = QTimer(self)
            self._nest_timer.timeout.connect(self._nest_tick)
        if running:
            # live clock: the status changes every second even while the engine finds nothing shorter
            st = self.project.nest_settings if self.project else None
            self._nest_total = (st.time_limit if st else 0) * max(1, getattr(st, "best_of", 1) or 1)
            self._nest_t0 = time.monotonic()
            self._last_prog = {}
            self._nest_timer.start(1000)
            self._nest_tick()
        else:
            self._nest_timer.stop()

    def _nest_tick(self):
        if getattr(self, "_nest_t0", None) is None or getattr(self, "_stopping", False):
            return
        el = time.monotonic() - self._nest_t0
        tot = getattr(self, "_nest_total", 0) or 0
        d = getattr(self, "_last_prog", {}) or {}
        L = d.get("length")
        msg = tr("running_live", t=el, T=tot, len=self._fmt_len(L) if L else "—")
        if not L and d.get("placing"):            # first layout of a big job: pieces placed so far
            msg += "  · " + tr("first_layout", k=d["placing"], n=d["of"])
        if d.get("attempts", 1) > 1:
            msg = tr("attempt_of", k=d["attempt"], n=d["attempts"]) + "  " + msg
        if d.get("engine") == "sparrow":
            msg += "  · sparrow"
        elif getattr(self, "_engine_note", ""):
            msg += "  · " + tr("eng_builtin_only", why=self._engine_note)
        self.statusBar().showMessage(msg)
        if tot > 0:
            self.progress_bar.setValue(min(99, int(100 * el / tot)))

    def _set_parallel(self, n):
        NEST_SLOTS.set_limit(n)
        self.settings_store.setValue("parallel_nests", n)
        for w in self._all_windows():               # same value in every session window
            if w is not self:
                w.f_parallel.blockSignals(True)
                w.f_parallel.setValue(n)
                w.f_parallel.blockSignals(False)

    def _nest_waiting(self, on):
        if on:                                   # the clock starts when the run really starts
            self._nest_t0 = None
            self.statusBar().showMessage(tr("nest_waiting"))
        else:
            self._nest_t0 = time.monotonic()
            self.statusBar().showMessage(tr("nest_started"))

    def stop_nesting(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            # answer at once: the run ends within a second; previews of the running layout are not drawn any more
            self._stopping = True
            self.btn_stop.setEnabled(False)
            self._pending_preview = None
            self.statusBar().showMessage(tr("nest_stopping"))
            self.statusBar().repaint()          # (no processEvents here: re-entering the event loop in a click)
            _nest_log("stop pressed")
            w = self.worker
            QTimer.singleShot(20000, lambda: self._stop_watch(w))
        elif self.view.pick_match:              # Esc also ends picking plaid match points
            self.plaid.b_pick.setChecked(False)
        elif self.view.measure_mode:            # Esc is also 'clear measurement'
            self.view.clear_measure()

    def _busy(self) -> bool:
        """Nesting runs: the canvas shows the live preview, which must not be edited."""
        return bool(self.worker and self.worker.isRunning())

    PREVIEW_INTERVAL_MS = 600

    def on_progress(self, d):
        """Live preview, coalesced: at most one redraw per PREVIEW_INTERVAL_MS however fast results arrive."""
        if not d.get("final"):
            self._last_prog = d
            self._nest_tick()
        if getattr(self, "_stopping", False):
            return
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
        self.strip.set_data(self.project, tmp)      # the strip follows the live result (placed = not to place)
        self._strip_height()

    def on_finished(self, marker, info):
        _nest_log(f"finished: stopped={info.get('stopped')} engine={info.get('engine')} "
                  f"placed={sum(1 for p in marker.placements if p.placed)}/{len(marker.placements)}")
        self._synced_order = self._order_signature() if self.project is not None else None
        self._nest_ui(False)
        if info.get("stopped") and not any(p.placed for p in marker.placements):
            # stopped before a first complete layout: keep the marker on screen, add nothing
            self.statusBar().showMessage(tr("nest_stopped_empty"))
            if self.marker is not None:
                self.view.show_marker(self.project, self.marker)
                self.after_edit()
            return
        self.mark_dirty()
        self.project.markers.append(marker)
        self.refresh_markers_list(select=len(self.project.markers) - 1)
        v = info["validation"]
        msg = tr("done", v=self.issues_summary(v, one_line=True))
        if info.get("attempts"):
            msg = tr("best_done", n=len(info["attempts"]),
                     l=" / ".join(f"{L:.0f}" for _s, L, _ok in info["attempts"]), b=marker.length) + " | " + msg
        if info.get("warnings"):
            msg += " | " + "; ".join(info["warnings"])
        if info.get("cut_short"):
            msg = tr("nest_cut_short", n=info["cut_short"]) + " | " + msg
            if not info.get("stopped"):         # not modal: a blocking box (maybe behind the window) froze it
                box = QMessageBox(QMessageBox.Warning, tr("run"), tr("nest_cut_short", n=info["cut_short"]),
                                  parent=self)
                box.setAttribute(Qt.WA_DeleteOnClose)
                box.setModal(False)
                box.show()
        self.statusBar().showMessage(msg)

    # -- validation messages -----------------------------------------------------------------
    def issues_summary(self, v, one_line=False) -> str:
        """Readable result of the marker check: 'valid' or one line per kind of problem with the pieces' names."""
        if v.ok:
            return tr("v_ok", n=v.checked)
        names = {pl.uid: f"{self.project.piece(pl.piece_uid).name} {pl.size}" for pl in self.marker.placements} \
            if self.marker else {}
        lines = []
        for kind in dict.fromkeys(i.kind for i in v.issues):
            iss = [i for i in v.issues if i.kind == kind]
            who = list(dict.fromkeys(names.get(u, u) for i in iss for u in i.placements))
            more = f" … (+{len(who) - 6})" if len(who) > 6 else ""
            lines.append(tr("v_line", what=tr("v_" + kind) if ("v_" + kind) in T else kind, n=len(iss))
                         + (": " + tr("v_sep").join(who[:6]) + more if who else ""))
        if one_line:
            return tr("v_bad") + " " + " | ".join(lines)
        return tr("v_bad") + "\n" + "\n".join("• " + ln for ln in lines)

    def _confirm_invalid(self, v, title) -> bool:
        """The marker has problems: show them (readable), offer to show the pieces on the marker or go on."""
        box = QMessageBox(QMessageBox.Warning, title, self.issues_summary(v) + "\n\n" + tr("export_anyway"),
                          parent=self)
        b_yes = box.addButton(tr("v_export_anyway"), QMessageBox.AcceptRole)
        b_show = box.addButton(tr("v_show"), QMessageBox.ActionRole)
        box.addButton(tr("cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(b_show)
        box.exec()
        if box.clickedButton() is b_show:
            uids = list(dict.fromkeys(u for i in v.issues for u in i.placements))
            self.view.show_pieces(uids)
            return False
        return box.clickedButton() is b_yes

    # -- export ----------------------------------------------------------------------------
    def export(self, fmt):
        if not self.marker:
            return
        v = self.validate_current()
        if v is not None and not v.ok and not self._confirm_invalid(v, tr("export").replace("&", "")):
            return
        from ..exporters.iso import MachineProfile
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
        elif fmt == "scb":
            from ..service import scb_template
            cfg = getattr(self, "scb_template_path", None) or scb_template(self.project)
            if cfg is None:
                QMessageBox.information(self, tr("save_scb"), tr("scb_pick_template"))
                cfg, _ = QFileDialog.getOpenFileName(self, tr("save_scb"), self.settings_store.value("last_dir", ""),
                                                     "GRAFIS SCB (*.scb *.SCB)")
                if not cfg:
                    return
                self.scb_template_path = cfg            # asked once per session
        ext = {"plt": "PLT (*.plt)", "dxf": "DXF (*.dxf)", "iso": "ISO (*.iso)", "scb": "GRAFIS SCB (*.scb)"}[fmt]
        name = f"{self.project.name}_{self.marker.fabric.width:g}{'_DIAGNOSTIC' if diagnostic else ''}.{fmt}"
        p, _ = QFileDialog.getSaveFileName(self, tr("export").replace("&", ""),
                                           os.path.join(self.settings_store.value("export_dir", ""), name), ext)
        if not p:
            return
        try:
            export_marker(self.project, self.marker, fmt, p, cfg, diagnostic_iso=diagnostic)
        except Exception as e:
            QMessageBox.critical(self, tr("export").replace("&", ""), str(e))
            return
        self.settings_store.setValue("export_dir", os.path.dirname(p))
        self.statusBar().showMessage(tr("exported", p=p))
        if fmt == "scb":
            QMessageBox.information(self, tr("save_scb"), tr("scb_saved", p=p))

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
        if self.dirty and self.project is not None and not getattr(self, "_closing_for_update", False):
            r = QMessageBox.question(self, tr("unsaved_title"), tr("unsaved_text", n=self.project.name),
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save()):
                ev.ignore()
                return
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set()
            # a deleted running QThread would abort the application - but waiting without end froze the close
            # when a run was stuck (hang.log): after 5 s it is kept alive outside the window (app.py ends it)
            if not self.worker.wait(5000):
                _nest_log("close: run still going 5 s after stop - left to finish in the background")
                self.worker.setParent(None)
                ORPHAN_WORKERS.append(self.worker)
        dlg = getattr(self, "_batch_dlg", None)
        try:
            if dlg is not None:
                dlg.stop_and_wait()
        except RuntimeError:                    # dialog already deleted
            pass
        if self.sessions is not None:
            self.sessions.remove(self)
        super().closeEvent(ev)


_ = (math, QAbstractItemView)
