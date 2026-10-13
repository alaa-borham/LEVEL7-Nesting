# Dependencies and licences

| Package | Version (tested) | Licence | Use |
|---|---|---|---|
| Python | 3.12 (Windows CI), 3.13 (Linux dev) | PSF | runtime (bundled) |
| shapely | 2.2.0 | BSD-3-Clause | polygon validation, buffers, union |
| pyclipper (Clipper 6) | 1.4.0 | MIT / Boost | Minkowski NFP, polygon boolean ops |
| ezdxf | 1.4.4 | MIT | DXF write/read |
| PySide6-Essentials (Qt 6) | 6.12.0 | LGPL-3.0 | GUI; shipped as separate DLLs (dynamic linking) — Qt can be replaced by the user |
| numpy | 2.5.4 | BSD-3-Clause | shapely dependency |
| PyInstaller | 6.20.0 (build only) | GPL-2.0 + bootloader exception | freezing; the exception allows distributing the output |
| Inno Setup 6 | build only | Inno Setup licence (free) | Setup.exe |
| pytest | 9.1.1 (dev) | MIT | tests |

No cloud or AI service is used by the application; it runs offline.
LGPL note: the installer contains unmodified Qt/PySide6 libraries as separate files; include the
LGPL text and a note on how to obtain the Qt source when redistributing.

## Optional nesting engine
* **sparrow** (MIT, J. Gardeyn / KU Leuven) with **jagua-rs** (MPL-2.0): built by CI from a pinned commit and
  bundled as `engines/sparrow.exe`; run as a separate process. Licence notices: THIRD_PARTY_LICENSES.md.
  Without it LEVEL7 uses only its own engine.

## Marker order lists
* **openpyxl** 3.1.5 (MIT): reading / writing Excel (.xlsx) marker order lists. CSV lists need no extra package.
