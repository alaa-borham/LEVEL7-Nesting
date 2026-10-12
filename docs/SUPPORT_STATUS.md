# Actual support status and limitations (v0.1.0)

## GRAFIS reading — native, no GRAFIS installation or licence needed

| Item | Status |
|---|---|
| Signature, size, SHA-256, block chain, damaged-file diagnosis | done, tested (incl. truncated / corrupted blocks) |
| Text sections, sizes, parts, IDs, Arabic names (cp1256) | done, tested |
| Cut contour per part and size (MDL, all 14 sizes + base) | probable method, verified against GRAFIS cut flags for size 44 |
| Cut contour of nested size (SCB) | confirmed (GRAFIS flags) |
| Seam line, internal lines, notches, grain line, text | read; roles are probable interpretations |
| Symbols (kind 6) | position + code read; meaning unknown → layer MARK only, never drilled/cut |
| SCB placements: position, rotation, mirror, bundle, copies | reproduced exactly (efficiency/area/length = GRAFIS) |
| Spline definitions, construction program | not read (GRAFIS stores evaluated polylines, which are used) |
| Writing MDL/SCB | not supported (format not proven) |
| Absolute left/right of the SCB marker | needs a GRAFIS screenshot to confirm |

## Nesting
Irregular/concave pieces via no-fit polygons (pyclipper Minkowski), bottom-left placement, genetic
search over order/rotation, parallel seeds, time limit, seed, stop-with-best, progress, background
worker. Constraints: no overlap, usable width, margins, spacing, grain parallel to length (0/180,
90 only if explicitly allowed), mirror only for mirrored copies, pinned pieces, material groups,
copies/sizes preserved, unplaceable pieces reported with reason, no scaling.
Lay types: open; face-to-face and folded produce pairs (folded halves the width) — **cut-on-fold
pieces are not supported** (fold edges are not identified in the source).
Nesting inside piece holes: disabled. No optimality is claimed. Measured: at 1430 mm the original
GRAFIS marker is 2929.9 mm; LEVEL7 reaches 2960.5 mm in 60 s (≈1 % longer).

## Export
* PLT/HP-GL: 1:1 (40 units/mm default, configurable), pens per layer, labels via `LB`, closure and
  range checks; verified by re-reading. Not yet verified on the user's plotter → `verified_with_device=false`.
* DXF: generic R2000, mm, separate layers; vertex-exact. Not labelled AAMA/ASTM.
* ISO: **not configured** — only a diagnostic preview (marked NOT FOR PRODUCTION).

## Windows
The CI workflow builds and tests on `windows-2022` (PyInstaller + Inno Setup Setup.exe, silent install,
desktop shortcut check). Results are only claimed for runs that actually passed on GitHub Actions.

## Information still needed (what each item settles)
1. **Screenshot of `Neay blue pants-44.scb` in GRAFIS marker view** → confirms left/right (mirror and
   Y-axis direction) of the reconstructed marker.
2. **DXF (or AAMA/ASTM) export from GRAFIS of the same MDL, all sizes** → independent vertex-level
   check of contours, notches, grain lines and text positions in every size (now verified only for
   size 44 by GRAFIS' own cut flags).
3. **Same model saved as SCB with another width (e.g. 1500)** → confirms placement-field semantics
   (rotation/flag bits) on a second layout.
4. **A PLT file produced by GRAFIS for your plotter + plotter model** → units, origin, axis direction,
   pen numbers for the plotter configuration.
5. **Cutting machine brand/model + a reference ISO file or its programming manual** → enables a
   verified ISO post-processor.
6. **What the symbol codes (e.g. 221, 311) mean in your GRAFIS setup** → drill holes vs. reference marks.
