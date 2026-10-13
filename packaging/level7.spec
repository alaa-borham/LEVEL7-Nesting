# PyInstaller spec for LEVEL7 Nesting (Windows 10/11 x64, onedir build).
# Build:  pyinstaller packaging/level7.spec --noconfirm
# Output: dist/LEVEL7Nesting/LEVEL7Nesting.exe (+ level7-cli.exe)
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "level7", "resources", "level7.ico")
datas = [(os.path.join(ROOT, "level7", "resources"), "level7/resources"),
         (os.path.join(ROOT, "docs"), "docs")]
hidden = ["shapely", "pyclipper", "ezdxf", "level7.nesting.parallel", "PySide6.QtNetwork"]
excl = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf", "tkinter", "matplotlib"]

# optional sparrow nesting engine (built by CI from a pinned commit into engines/)
SPARROW = os.path.join(ROOT, "engines", "sparrow.exe" if os.name == "nt" else "sparrow")
engine_bins = [(SPARROW, "engines")] if os.path.isfile(SPARROW) else []
gui = Analysis([os.path.join(ROOT, "packaging", "run_gui.py")], pathex=[ROOT], datas=datas, binaries=engine_bins,
               hiddenimports=hidden,
               excludes=excl, noarchive=False)
cli = Analysis([os.path.join(ROOT, "packaging", "run_cli.py")], pathex=[ROOT], datas=[], binaries=engine_bins,
               hiddenimports=hidden,
               excludes=excl + ["PySide6"], noarchive=False)

gui_pyz = PYZ(gui.pure)
cli_pyz = PYZ(cli.pure)
gui_exe = EXE(gui_pyz, gui.scripts, [], exclude_binaries=True, name="LEVEL7Nesting", icon=ICON, console=False,
              version=None)
cli_exe = EXE(cli_pyz, cli.scripts, [], exclude_binaries=True, name="level7-cli", icon=ICON, console=True)
coll = COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="LEVEL7Nesting")
