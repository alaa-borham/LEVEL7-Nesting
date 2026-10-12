# LEVEL7 Nesting

Windows desktop application (PySide6) that reads **GRAFIS MDL and SCB files natively** (no GRAFIS
installation needed), nests irregular garment pieces for a given fabric width and quantities, lets the
user edit the marker by mouse, and exports **PLT (HP-GL), DXF and ISO (diagnostic only until a machine
profile is verified)**.

Arabic guide: [docs/دليل_التثبيت_والتشغيل.md](docs/دليل_التثبيت_والتشغيل.md) ·
Format notes: [docs/GRAFIS_FORMAT.md](docs/GRAFIS_FORMAT.md) ·
Support status and limitations: [docs/SUPPORT_STATUS.md](docs/SUPPORT_STATUS.md) ·
Test results: [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) · Dependencies: [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)

## Key results on the supplied samples
* Both files parse completely (558 / 445 blocks, exact length chain); 4155/4155 polylines verified.
* MDL: 19 parts (11 production), 14 sizes 28–54, graded geometry per size (not uniform scaling).
* SCB `Neay blue pants-44.scb`: the original marker (28 pieces, 2 bundles of size 44) is reconstructed
  with zero overlap, grain lines parallel to the length, and **efficiency 83.86 % / area 3.51 m² /
  length 2929.93 mm — identical to the GRAFIS values**.
* New nesting (60 s, 4 workers): 1400 mm → 3042 mm, 1430 mm → 2961 mm, 1500 mm → 2840 mm, all validated.

## Layout
```
level7/formats/grafis   container, text sections, geometry, placements, contour (readers/grafis_mdl+scb)
level7/readers          grafis.py (MDL/SCB), dxf.py (generic DXF import path)
level7/geometry         transforms, search approximations
level7/nesting          NFP primitives, engine (GA + bottom-left), parallel runner
level7/validation       independent checker + statistics
level7/exporters        scene, plt, dxf, iso
level7/project_storage  .l7n project files (versioned JSON in ZIP)
level7/diagnostics      inspector (level7-inspect)
level7/ui               PySide6 GUI
packaging/              PyInstaller spec, Inno Setup script, build_windows.ps1
.github/workflows       Windows build + test + installer + silent install test
```

## Run from source
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt && pip install -e .
level7-gui                      # desktop app
level7-inspect samples\*.mdl samples\*.scb -o reports
python -m pytest -q
```

## Build the installer
`powershell -File packaging\build_windows.ps1` → `dist\installer\LEVEL7Nesting-<ver>-Setup.exe`
(also produced by GitHub Actions as artifact `LEVEL7Nesting-Setup`).
