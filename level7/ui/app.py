"""Entry point of the desktop application."""
from __future__ import annotations

import multiprocessing
import os
import sys


def log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "LEVEL7 Nesting", "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _install_diagnostics(app):
    """Crash and hang log: unhandled exceptions are appended to errors.log; if the window thread is blocked
    for more than HANG_SECONDS, the stack of every thread is written to hang.log (send it to support)."""
    import datetime
    import faulthandler
    import traceback
    from PySide6.QtCore import QTimer
    HANG_SECONDS = 15
    try:
        d = log_dir()
        hang = open(os.path.join(d, "hang.log"), "a", encoding="utf-8")
    except OSError:
        return
    hang.write(f"\n=== LEVEL7 started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
    hang.flush()
    faulthandler.enable(file=hang)

    def heartbeat():
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(HANG_SECONDS, repeat=False, file=hang)
    t = QTimer(app)
    t.timeout.connect(heartbeat)
    t.start(1000)
    heartbeat()
    app._diag = (t, hang)

    def hook(et, ev, tb):
        try:
            with open(os.path.join(d, "errors.log"), "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
                fh.write("".join(traceback.format_exception(et, ev, tb)))
        except OSError:
            pass
        sys.__excepthook__(et, ev, tb)
    sys.excepthook = hook


def main(argv=None):
    multiprocessing.freeze_support()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("LEVEL7 Nesting")
    app.setOrganizationName("LEVEL7")
    app.setStyle("Fusion")
    icon = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "level7.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    _install_diagnostics(app)
    w = MainWindow()
    w.show()
    for a in argv[1:]:
        if os.path.isfile(a):
            w.open_path(a)
            break
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
