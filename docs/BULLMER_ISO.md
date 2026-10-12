# Bullmer cut file (GRAFIS "Bullmer-Cutter (typical)") — as reproduced by LEVEL7

Reference: `samples/reference/Neay blue pants-44-1500.iso`, written by GRAFIS (Cutter output →
"Bullmer-Cutter (typical)", options: cut notches ✔, set drill holes ✔, everything else off; see
`docs/evidence/grafis_cutter_output_bullmer.png`) for the 1500 mm marker `Neay blue pants-44-1500.scb`.

## Format (derived from the reference file)

| Element | Form | Meaning |
|---|---|---|
| Line end | CRLF; each block ends with `*` | |
| Header | `H1*G71*M70*D2*M15*` | constant |
| Job line | `M20*<NAME>/L=<length m, 2 dec>m/B=<width m, 2 dec>m*` | NAME = job name upper-case, spaces removed |
| Piece start | `N<k>*` then `D2*M15*` | k = 1…n, tool D2, knife up |
| Coordinates | `X<int>Y<int>*` | 0.1 mm, absolute, X = marker length, Y = width, origin lower-left |
| Knife | `M14*` down, `M15*` up | |
| Notch | … base, tip, `M15*`, base, `M14*` … | knife plunges 5 mm inward and returns |
| End | last piece ends `M15*D4*M00*` | |

Rules confirmed against all 28 pieces of the reference:
* contours are cut **clockwise**;
* the cut starts at the **cut-line element junction nearest to the top-right corner** of the piece's
  bounding box (28/28);
* vertices closer than **2.0 mm** to the previous kept vertex are omitted (kept ≥ 2.3 mm, dropped ≤ 1.73 mm in
  the reference); a notch on an omitted vertex is cut from the last kept vertex;
* no drill commands occur in the reference although "set drill holes" was on → consistent with the symbols
  being measurement annotations (values = #TFLIST), not drill holes.

## Verification (`tests/test_grafis_reference_bullmer.py`)
LEVEL7's file for the same marker (geometry read from the SCB only): same header/job line/end, same block
types, 28 pieces, 1520 lines; per piece the same number of knife strokes, same start point, direction and
number of points; 1308 of 1318 coordinates identical, the other 10 differ by one 0.1 mm unit.

**Not reproduced:** GRAFIS' piece order (heuristic unknown). LEVEL7 orders pieces in 400 mm bands along the
length, bottom to top. Piece order changes the sequence of cutting, not what is cut.

**IECHO:** the user sends this same file to the IECHO cutter; LEVEL7's "IECHO" profile writes the identical
file (`--iso-preset iecho`).

**Before production:** cut one marker on the Bullmer and compare; then set `device_tested`.
