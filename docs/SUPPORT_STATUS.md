# Actual support status and limitations (v0.2.x)

## GRAFIS reading — native, no GRAFIS installation or licence needed

| Item | Status |
|---|---|
| Signature, size, SHA-256, block chain, damaged-file diagnosis | done, tested (incl. truncated / corrupted blocks) |
| Text sections, sizes, parts, IDs, Arabic names (cp1256) | done, tested |
| Cut contour per part and size (MDL, all 14 sizes + base) | probable method, verified against GRAFIS cut flags for size 44 |
| Cut contour of nested size (SCB) | confirmed (GRAFIS flags) |
| Cut contour, notches, seam line, size texts | identical to GRAFIS' own DXF export for size 44 (cut < 0.001 mm) |
| Grain line, size texts — all 15 sizes | identical to GRAFIS piece DXF exports (parts 007, 009, 010, 011, 012) |
| Cut contours of all 14 sizes + base | **confirmed** against GRAFIS' AAMA export (DXF + RUL): all 165 grade points × 14 sizes lie on LEVEL7's MDL contours within 0.007 mm (RUL precision); base identical (< 0.001 mm) |
| Internal lines | read; not yet compared with a GRAFIS export |
| Symbols (kind 6) | **confirmed: measurement annotations** — all 615 values equal the #TFLIST measurement of the same size (e.g. "414", "I=342", "300 (2*)"); layer MEASURE (screen/DXF only), never plotted, drilled or cut. GRAFIS exports no drill holes for them (Bullmer ISO, AAMA) |
| SCB placements: position, rotation, mirror, bundle, copies | reproduced exactly (efficiency/area/length = GRAFIS) |
| Spline definitions, construction program | not read (GRAFIS stores evaluated polylines, which are used) |
| Writing SCB (marker file) | **experimental**: template based (a GRAFIS SCB of the same model); unknown GRAFIS data copied byte for byte, only the marker block and #SBINFO/#SBGRLST/#SBTLIST rewritten. GRAFIS' own markers are rewritten byte-identical (3 files), LEVEL7 markers are re-read identically by LEVEL7. Not yet confirmed by opening in GRAFIS |
| Writing MDL | not supported |
| Absolute left/right of the SCB marker | confirmed against the GRAFIS screen view (docs/evidence) |

## Nesting
Irregular/concave pieces via no-fit polygons (pyclipper Minkowski), bottom-left placement, genetic
search over order/rotation, parallel seeds, time limit, seed, stop-with-best, progress, background
worker. Constraints: no overlap, usable width, margins, spacing, grain parallel to length (0/180,
90 only if explicitly allowed), mirror only for mirrored copies, pinned pieces, material groups,
copies/sizes preserved, unplaceable pieces reported with reason, no scaling.
Lay types: open; face-to-face and folded produce pairs (folded halves the width) — **cut-on-fold
pieces are not supported** (fold edges are not identified in the source).
Nesting inside piece holes: disabled. No optimality is claimed. Measured: at 1430 mm the original
GRAFIS marker is 2929.9 mm; LEVEL7 reaches 2960.5 mm in 60 s (≈1 % longer). At 1500 mm GRAFIS
nested 2849.9 mm / 82.19 % (`Neay blue pants-44-1500.scb`) and LEVEL7 2840.2 mm / 82.48 % in 60 s.
GRAFIS options: "Right-Left" spreading = LEVEL7 open lay with mirrored copies; "Two way" = 180° allowed;
"One way" = untick 180°; "Same sizes – same direction" is **not implemented yet**.

## Export
* PLT/HP-GL: 1:1 (40 units/mm default, configurable), pens per layer, labels via `LB`, closure and
  range checks; verified by re-reading.
* PLT profile **"Algotex (GRAFIS-compatible)"**: same file dialect as GRAFIS' PLT for the user's Algotex
  (CRLF lines, `IN`/`LT1`/`PA`/`PD`/`PU`/`PG`, 40 units/mm, x = length, y = width, origin lower-left,
  notches as 5 mm spikes in the cut line, seam notches in the seam line, texts as strokes). Compared with
  GRAFIS' PLT of the 1500 marker: 28 cut contours and 44/44 notch slits within the 0.025 mm grid, seam
  lines identical, texts at the same places (glyph shapes differ). Not yet cut on the device →
  `verified_with_device=false` until a 1:1 test (calibration square) is cut and measured.
* DXF: generic R2000, mm, separate layers; vertex-exact. Not labelled AAMA/ASTM.
* AAMA import (DXF + RUL, as written by GRAFIS): pieces, all sizes, notches (layer 4), seam lines (layer 14),
  grain (layer 7), material, quantity, Arabic names. Grade points exact; non-graded curve points are
  interpolated linearly → graded sizes are approximate (front up to ≈5 mm off GRAFIS' own curve grading);
  the native MDL reader is exact and remains the reference path. Opened automatically when a `.rul` sits
  next to the `.dxf`. Not labelled as a full AAMA/ASTM implementation.
* DXF import: generic + GRAFIS DXF exports (blocks exploded, layer 1 cut with notch spikes, layer 8
  seam). GRAFIS' marker DXF has no grain lines → grain must be set per piece before nesting.
* ISO **Bullmer** (GRAFIS "Bullmer-Cutter (typical)" compatible): reproduces GRAFIS' cut file for the
  reference marker line for line (1308/1318 coordinates identical, rest ±0.1 mm; same starts, direction,
  notch plunges) — only the piece order differs. See docs/BULLMER_ISO.md. Not yet test-cut on the machine.
* ISO other machines: diagnostic preview only (marked NOT FOR PRODUCTION).

## Windows
* Online update: every successful build of the default branch publishes GitHub Release `v0.2.<build>`
  (installer + SHA256SUMS.txt). The app checks `releases/latest` at start-up and every 6 h (can be switched off),
  notifies, downloads from github.com over HTTPS, verifies SHA-256, asks to save, runs the installer
  (`/SILENT /CLOSEAPPLICATIONS /LAUNCH=1`) and restarts. Installer is not code-signed (SmartScreen/UAC prompt).
  Installs of 0.1.0 have no updater: install 0.2.x once by hand.
The CI workflow builds and tests on `windows-2022` (PyInstaller + Inno Setup Setup.exe, silent install,
desktop shortcut check). Results are only claimed for runs that actually passed on GitHub Actions.

## Information still needed (what each item settles)
1. ~~Screenshot of the marker in GRAFIS~~ — received; orientation confirmed.
2. ~~All-size verification~~ — received (piece DXFs + AAMA DXF/RUL): cut contours, grain lines and texts
   verified in all sizes.
3. ~~The 1500 mm GRAFIS marker as SCB~~ — received; decoded with the same rules and identical to GRAFIS.
4. ~~GRAFIS PLT for the plotter~~ — received (Algotex); profile implemented and compared. Still needed:
   **cut/plot `examples/calibration_1000mm_square_algotex.plt` on the Algotex and measure it.**
5. ~~Bullmer reference cut file~~ — received (GRAFIS "Bullmer-Cutter (typical)"); profile implemented and
   matched. Still needed: **a test cut of `examples/nested_1500_bullmer.iso` (or any marker) on the Bullmer.**
   Second cutter: **IECHO (China)** — the user feeds it the same file GRAFIS writes for the Bullmer, so
   LEVEL7 offers an "IECHO" profile that writes exactly the Bullmer file. Needs its own test cut on the IECHO.
6. ~~Meaning of the symbol codes (e.g. 221, 311)~~ — resolved from the data: they are measurement values
   (equal to the GRAFIS measurement table, 615/615), not drill holes.
