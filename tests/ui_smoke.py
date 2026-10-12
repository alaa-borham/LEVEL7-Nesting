"""Headless GUI smoke test (QT_QPA_PLATFORM=offscreen). Run: python tests/ui_smoke.py OUTDIR"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
