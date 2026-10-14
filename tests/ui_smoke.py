"""Headless GUI smoke test (QT_QPA_PLATFORM=offscreen). Run: python tests/ui_smoke.py OUTDIR"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):                  # Arabic messages on a Windows cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("LEVEL7_NO_UPDATE_CHECK", "1")   # never open an update dialog during the smoke test
HERE = os.path.dirname(os.path.abspath(__file__))
SCB = os.path.join(HERE, "..", "samples", "Neay blue pants-44.scb")


def main(outdir):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    QMessageBox.critical = staticmethod(lambda *a, **k: print("CRITICAL:", a[1:]))
    app = QApplication([])
    from level7.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 900)
    w.show()
    w.open_path(SCB)
    app.processEvents()
    w.view.zoom_fit()
    app.processEvents()
    w.grab().save(os.path.join(outdir, "ui_original_marker.png"))
    assert w.marker is not None and w.marker.origin == "original"
    # fit mode must not refit in a loop: scroll bars that came and went resized the view, which refit it again
    # (15 000 refits in 30 s of nesting kept the interface busy and delayed every click, Stop included)
    from PySide6.QtCore import Qt
    assert w.view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert w.view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    first = w.issues_list.item(0).text()
    print("original:", first)
    w.f_width.setValue(1500)
    w.f_time.setValue(8)
    w.run_nesting()
    loop = QEventLoop()
    w.worker.finished.connect(loop.quit)
    QTimer.singleShot(120000, loop.quit)
    loop.exec()
    app.processEvents()
    assert len(w.project.markers) == 2, "nesting did not produce a marker"
    print("nested:", w.marker.name, round(w.marker.length, 1), w.issues_list.item(0).text())
    w.view.zoom_fit()
    app.processEvents()
    w.grab().save(os.path.join(outdir, "ui_nested_1500.png"))
    pl = next(p for p in w.marker.placements if p.placed)
    w.on_moved([(pl, 60.0, 0.0)])
    moved = w.issues_list.item(0).text()
    print("after manual move:", moved)
    w.undo.undo()
    print("after undo:", w.issues_list.item(0).text())
    from level7.ui.display_options import DisplayOptionsDialog
    dlg = DisplayOptionsDialog(w.view.options, w)
    dlg.boxes["grain"].setChecked(True)
    dlg.boxes["marking"].setChecked(True)
    w.view.set_options(**dlg.result_options())
    app.processEvents()
    print("status:", w.grafis_status.text())
    w.grab().save(os.path.join(outdir, "ui_display_options.png"))
    dlg.show()
    app.processEvents()
    dlg.grab().save(os.path.join(outdir, "ui_display_dialog.png"))
    dlg.close()
    w.toggle_language()
    app.processEvents()
    w.grab().save(os.path.join(outdir, "ui_english.png"))
    # several sessions: one window per file, at most MAX_WINDOWS
    from PySide6.QtWidgets import QMessageBox
    from level7.ui.sessions import MAX_WINDOWS, SessionManager
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    sm = SessionManager(app)
    first = sm.new_window(show=False)
    sm.open_files([SCB] * (MAX_WINDOWS + 1), prefer=first)
    app.processEvents()
    assert len(sm.windows) == MAX_WINDOWS and all(x.project is not None for x in sm.windows), "sessions"
    for x in list(sm.windows):
        x.close()
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
