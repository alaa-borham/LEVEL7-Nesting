"""Entry point of the desktop application."""
from __future__ import annotations

import multiprocessing
import os
import sys


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
    w = MainWindow()
    w.show()
    for a in argv[1:]:
        if os.path.isfile(a):
            w.open_path(a)
            break
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
