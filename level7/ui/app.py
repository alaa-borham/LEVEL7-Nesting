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

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("LEVEL7 Nesting")
    app.setOrganizationName("LEVEL7")
    from PySide6.QtCore import QSettings
    from .themes import apply_theme
    apply_theme(str(QSettings("LEVEL7", "Nesting").value("theme", "dark")))
    icon = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "level7.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    files = [a for a in argv[1:] if os.path.isfile(a)]
    from .sessions import SessionManager, acquire_primary, forward_to_primary
    lock = acquire_primary()
    if lock is None and forward_to_primary(files):
        return 0                       # an open LEVEL7 takes the files (one session window per file)
    _install_diagnostics(app)
    sessions = SessionManager(app)
    app._level7 = (lock, sessions)     # keep the lock for the lifetime of the program
    if lock is not None:
        sessions.listen()
    w = sessions.new_window()
    if files:
        sessions.open_files(files, prefer=w)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
