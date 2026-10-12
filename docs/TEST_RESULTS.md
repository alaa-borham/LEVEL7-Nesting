# Test results

## Automated tests (`python -m pytest -q`) — 34 passed
Linux (Python 3.13, dev container) and Windows (GitHub Actions `windows-2022`, Python 3.12;
see the `windows-build` workflow runs for the current status).

| Area | Test | Checks |
|---|---|---|
| Import | container chain, SHA-256, sizes | exact chain, header length, both files |
| Import | damaged files | non-GRAFIS, truncated, broken marker, bad length, bad record count → diagnosed, no crash |
| Import | SCB text | WIDTH/LENGTH/EFFCNCY/USDAREA/PIECES/BUNDLES/PCSTOTAL/PCSUNPLC/MODEL/MATERIALO, Arabic names |
| Import | MDL sizes/parts | 28–54, `__HN40_0…__HN53_0`, 19 parts, shared IDs, material groups |
| Geometry | 4155 polylines | points == stored bbox (both files) |
| Geometry | MDL vs GRAFIS cut flags | identical contours for 9/9 placed parts (size 44) |
| Geometry | grading | per-size areas increase; non-uniform scaling |
| Geometry | grain, units | grain read for all production parts; mm evidence |
| Marker | original reconstruction | valid, eff 83.86 %, 3.51 m², 2929.93 mm |
| Marker | types vs copies | 9 types, 28 copies, mirrored = bundles × mirror column (independent of #SBTLIST) |
| Nesting | widths 1400/1430/1500 | valid, 28 copies, areas unchanged, inside width |
| Nesting | spacing 5 mm + margins | validated by distance check |
| Nesting | piece wider than fabric | reported unplaced with reason, not scaled |
| Nesting | pinned piece | stays in place |
| Nesting | stop | returns best valid layout |
| Nesting | seed | same seed + evaluations → identical layout |
| Nesting | face-to-face lay | pairs + warning for single parts |
| Export | PLT 1000 mm square | `PD40000,0,…` and re-read exact |
| Export | PLT marker | cut paths ≤ 0.0177 mm (0.025 mm grid), seams/text never on the cut pen, labels as LB |
| Export | DXF | vertex-exact re-read, $INSUNITS=4, layers, texts on TEXT |
| Export | ISO | refused without verified profile; diagnostic preview simulated back ≤ 0.0071 mm |
| Storage | .l7n | round trip without sources |
| CLI | non-UTF-8 console | regression for Windows cp1252 crash |
| GRAFIS DXF | `test_grafis_reference_dxf.py` | 28 cut contours < 0.01 mm (max 0.0008), 44/44 cut notches, seam + 24 seam notches, 16 texts |
| DXF import | `test_dxf_import.py` | GRAFIS DXF → 28 pieces, 46 notches; unknown grain refused with reason; nest after defining grain |
| GUI | `tests/ui_smoke.py` (offscreen) | open SCB, nest 1500, manual move flagged, undo, language switch |

## Nesting benchmark (examples/VERIFICATION.json; 60 s, seed 1, 4 processes)
| Width | Length (mm) | Utilisation (total width) | Validation |
|---|---|---|---|
| 1430 (original GRAFIS SCB) | 2929.93 | 83.86 % | valid |
| 1400 | 3042.2 | 82.50 % | valid |
| 1430 | 2960.5 | 83.00 % | valid |
| 1500 | 2840.2 | 82.48 % | valid |
| 1500 (GRAFIS SCB `-44-1500`) | 2849.93 | 82.19 % | valid (reconstructed) |

At 1430 mm LEVEL7 is ≈1 % longer than the saved GRAFIS marker after 60 s; at 1500 mm it is 9.7 mm
shorter than GRAFIS' own 1500 mm marker.

## Export verification (examples/VERIFICATION.json)
Every marker exported to PLT, DXF and diagnostic ISO and re-read: 28/28 cut paths each;
max deviation PLT 0.0172 mm, DXF 0.0 mm, ISO 0.0069 mm; calibration square sides 1000.000 mm.
Tolerance target 0.1 mm is met. Not yet verified on a physical plotter/cutter.
