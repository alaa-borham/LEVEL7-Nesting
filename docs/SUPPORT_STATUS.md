# Actual support status and limitations (v0.1.0)

## GRAFIS reading — native, no GRAFIS installation or licence needed

| Item | Status |
|---|---|
| Signature, size, SHA-256, block chain, damaged-file diagnosis | done, tested (incl. truncated / corrupted blocks) |
| Text sections, sizes, parts, IDs, Arabic names (cp1256) | done, tested |
| Cut contour per part and size (MDL, all 14 sizes + base) | probable method, verified against GRAFIS cut flags for size 44 |
| Cut contour of nested size (SCB) | confirmed (GRAFIS flags) |
| Cut contour, notches, seam line, size texts | identical to GRAFIS' own DXF export for size 44 (cut < 0.001 mm) |
| Internal lines, grain line | read; roles are probable (not contained in the GRAFIS DXF received) |
| Symbols (kind 6) | position + code read; meaning unknown → layer MARK only, never drilled/cut |
| SCB placements: position, rotation, mirror, bundle, copies | reproduced exactly (efficiency/area/length = GRAFIS) |
| Spline definitions, construction program | not read (GRAFIS stores evaluated polylines, which are used) |
| Writing MDL/SCB | not supported (format not proven) |
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
* DXF import: generic + GRAFIS DXF exports (blocks exploded, layer 1 cut with notch spikes, layer 8
  seam). GRAFIS' marker DXF has no grain lines → grain must be set per piece before nesting.
* ISO: **not configured** — only a diagnostic preview (marked NOT FOR PRODUCTION).

## Windows
The CI workflow builds and tests on `windows-2022` (PyInstaller + Inno Setup Setup.exe, silent install,
desktop shortcut check). Results are only claimed for runs that actually passed on GitHub Actions.

## Information still needed (what each item settles)
1. ~~Screenshot of the marker in GRAFIS~~ — received; orientation confirmed.
2. Size 44 verified against GRAFIS' DXF of the 1500 marker. Still useful: **a GRAFIS DXF of the
   pattern pieces in all sizes, with grain lines and internal lines switched on** → vertex-level check
   of the other 13 sizes, grain and internal lines.
3. ~~The 1500 mm GRAFIS marker as SCB~~ — received; decoded with the same rules and identical to GRAFIS.
4. ~~GRAFIS PLT for the plotter~~ — received (Algotex); profile implemented and compared. Still needed:
   **cut/plot `examples/calibration_1000mm_square_algotex.plt` on the Algotex and measure it.**
5. **Cutting machine brand/model + a reference ISO file or its programming manual** → enables a
   verified ISO post-processor.
6. **What the symbol codes (e.g. 221, 311) mean in your GRAFIS setup** → drill holes vs. reference marks.
