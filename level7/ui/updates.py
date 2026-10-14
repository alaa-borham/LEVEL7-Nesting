"""Update notification: background check at start-up and every few hours, download with progress, install."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QProgressDialog

from .. import __version__, updater
from .i18n import tr

CHECK_INTERVAL_MS = 6 * 3600 * 1000
FIRST_CHECK_DELAY_MS = 4000


class CheckThread(QThread):
    done = Signal(object, str)          # (UpdateInfo | None, error text)

    def run(self):
        try:
            self.done.emit(updater.check_latest(), "")
        except Exception as exc:
            self.done.emit(None, str(exc))


class DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(str, str)             # (path, error text)

    def __init__(self, info):
        super().__init__()
        self.info, self.cancel = info, False

    def run(self):
        try:
            p = updater.download(self.info, progress=lambda d, t: self.progress.emit(d, t),
                                 cancelled=lambda: self.cancel)
            self.done.emit(p, "")
        except Exception as exc:
            self.done.emit("", str(exc))


class UpdateManager(QObject):
    """Owned by the main window. ``before_install()`` lets the window save work; returns False to abort."""

    def __init__(self, window, settings, before_install):
        super().__init__(window)
        self.w, self.settings, self.before_install = window, settings, before_install
        self.thread = self.dl = None
        self.manual = False
        self.notified: set[str] = set()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.check(False))
        if self.auto_enabled():
            QTimer.singleShot(FIRST_CHECK_DELAY_MS, lambda: self.check(False))
        self.timer.start(CHECK_INTERVAL_MS)

    def auto_enabled(self) -> bool:
        return str(self.settings.value("updates/auto", "true")).lower() in ("true", "1")

    def set_auto(self, on: bool):
        self.settings.setValue("updates/auto", "true" if on else "false")

    def check(self, manual: bool):
        if (not manual and not self.auto_enabled()) or (self.thread and self.thread.isRunning()) or self.dl:
            return
        self.manual = manual
        if manual:
            self.w.statusBar().showMessage(tr("upd_checking"))
        self.thread = CheckThread()
        self.thread.done.connect(self._checked)
        self.thread.start()

    def _checked(self, info, err):
        manual, self.manual = self.manual, False
        if err:                                  # offline etc.: silent for automatic checks
            if manual:
                QMessageBox.warning(self.w, tr("updates"), tr("upd_failed", e=err))
            return
        if info is None:
            if manual:
                QMessageBox.information(self.w, tr("updates"), tr("upd_none", v=__version__))
            return
        skipped = self.settings.value("updates/skip", "")
        if not manual and (info.version == skipped or info.version in self.notified):
            return
        self.notified.add(info.version)
        self.w.statusBar().showMessage(tr("upd_available", v=info.version))
        self._notify(info)

    def _notify(self, info):
        box = QMessageBox(self.w)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(tr("updates"))
        box.setText(tr("upd_text", v=info.version, cur=__version__))
        notes = info.notes[:1500] + ("…" if len(info.notes) > 1500 else "")
        box.setInformativeText(tr("upd_info"))
        if notes:
            box.setDetailedText(notes)
        install = box.addButton(tr("upd_install"), QMessageBox.AcceptRole)
        box.addButton(tr("upd_later"), QMessageBox.RejectRole)
        skip = box.addButton(tr("upd_skip"), QMessageBox.DestructiveRole)
        auto = QCheckBox(tr("upd_auto"))
        auto.setChecked(self.auto_enabled())
        box.setCheckBox(auto)
        box.exec()
        self.set_auto(auto.isChecked())
        if box.clickedButton() is skip:
            self.settings.setValue("updates/skip", info.version)
        elif box.clickedButton() is install:
            self._download(info)

    def _download(self, info):
        self.dl = DownloadThread(info)
        dlg = QProgressDialog(tr("upd_downloading", v=info.version), tr("cancel"), 0, 100, self.w)
        dlg.setWindowTitle(tr("updates"))
        dlg.setMinimumDuration(0)
        dl = self.dl          # (self.dl is cleared when the download ends; closing the dialog then emits canceled)
        dlg.canceled.connect(lambda: setattr(dl, "cancel", True))

        def prog(d, t):
            dlg.setMaximum(t or 0)
            dlg.setValue(d if t else 0)
        self.dl.progress.connect(prog)
        self.dl.done.connect(lambda p, e: self._downloaded(dlg, p, e))
        self.dl.start()

    def _downloaded(self, dlg, path, err):
        canceled = self.dl.cancel
        self.dl = None
        dlg.close()
        if err:
            if not canceled:
                QMessageBox.warning(self.w, tr("updates"), tr("upd_failed", e=err))
            return
        if not self.before_install():
            return
        try:
            updater.start_installer(path)
        except Exception as exc:
            QMessageBox.warning(self.w, tr("updates"), tr("upd_failed", e=str(exc)))
            return
        QApplication.instance().quit()
