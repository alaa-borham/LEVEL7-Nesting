# Inspection report: Neay blue pants-44.scb

- size: 1,097,872 bytes
- SHA-256: `a96d5513c6c1349154105cfc63108774b987168712db74e5723b84d51d2d0f4c`
- signature: `GRAFIS-ModelldateiVB`
- blocks: 445
- structural errors: none

## Confirmed
- block chain: 445 blocks follow each other exactly via the length field (u32 units of 8 bytes) from offset 80 to the 'mdlEND_5' trailer; header u32[1]*8+8 == file size
- text sections in block (2,1,0,0), CRLF lines; #VERSION text = '1000' (meaning not known; not treated as GRAFIS program version)
- geometry blocks (3,part,7,size): 4155/4155 polyline elements decode to points whose bounding box equals the bbox stored in the element record
- placement block (2,8,0,0): 28 records of 120 bytes; reconstruction gives valid: 28 placements, no overlap/out-of-bounds/orientation issues, efficiency 83.86% (GRAFIS EFFCNCY 83.86), area 3.51 m2 (USDAREA 3.51), length 2929.93
- EFFCNCY definition = sum of placed cut areas / (WIDTH x LENGTH)
- rotation = base + extra + 180*(flags&0x80); mirror byte = mirrored copy, mirror about pattern Y axis before rotation; marker Y axis upward - identical piece positions, orientations and bundles (A/B) to the GRAFIS screen view of this marker (docs/evidence)
- internal MODEL name: 'PANTS Black.mdl' (differs from file name; informational only)

## Probable interpretations
- text encoding cp1256: Arabic part names decode to valid words
- cut contour (MDL) = largest closed cycle of whole polyline elements; matches the GRAFIS cut flags of the 44 marker for 9/9 placed parts and the same element set is chosen in all 15 grading entries
- units = millimetres: '#TFLIST' tables declare mm; part 7 size 44 has its hem line at y=-1040 and T2M4/T5M4 = 1040 for size 44; SCB WIDTH 1430 equals the max Y of the reconstructed marker; front length ~1135 is realistic only in mm
- style -7/-6 = seam (net) line, -3 = grain line, 2-point flagged style 1 = notch
- #SBTLIST columns = copies / mirrored copies per bundle (28 = 2 bundles x 14)

## Unknown
- header u32[0] and per-block u32 check value: not a byte sum, CRC-32 or Adler-32
- symbol elements (kind 6): position and code text read; meaning (drill hole, reference mark, ...) unknown -> exported only on layer MARK
- construction data blocks (3,k,2..6) are not interpreted; only evaluated geometry
- placement fields +28, +64..72 and flag bit 0x40

## Unsupported
- writing MDL/SCB files
- curve definitions: GRAFIS stores evaluated polylines; original spline parameters are not read

## Text sections
- `#VERSION` at file offset 184, 1 lines
- `#GRDTAB` at file offset 200, 15 lines
- `#TLIST` at file offset 455, 20 lines
- `#SBINFO` at file offset 1943, 17 lines
- `#SBGRLST` at file offset 2244, 2 lines
- `#SBTLIST` at file offset 2278, 9 lines
- `#ENDINFO` at file offset 2981, 1 lines

## Sizes
1:__HN40_0, 2:28, 3:30, 4:32, 5:34, 6:36, 7:38, 8:40, 9:42, 10:44, 11:46, 12:48, 13:50, 14:52, 15:54

## Parts
| # | name | production | material | count | mirrored | sizes with geometry | grain |
|---|---|---|---|---|---|---|---|
| 1 | bis | False |  |  |  | 15 | None |
| 2 | الصدر | False |  |  |  | 15 | None |
| 3 | 0 | False |  |  |  | 0 | None |
| 4 | basic | False |  |  |  | 15 | None |
| 5 | basic front | False |  |  |  | 15 | None |
| 6 | basic back | False |  |  |  | 15 | None |
| 7 | front | True | O | 1 | 1 | 15 | 90.0 |
| 8 | basic poket side | False |  |  |  | 15 | 90.0 |
| 9 | back | True | O | 1 | 1 | 15 | 90.0 |
| 10 | poket side | True | F | 1 | 1 | 15 | 90.0 |
| 11 | ورقه جيب الصدر | True | O | 1 | 1 | 15 | 90.0 |
| 12 | pants wist+4-5 | True | O | 1 | 0 | 15 | 90.0 |
| 13 | pants wist+10 | True | O | 1 | 0 | 15 | 90.0 |
| 14 | ziper LT | True | O | 1 | 0 | 15 | 90.0 |
| 15 | ziper RT | True | O | 1 | 0 | 15 | 90.0 |
| 16 | خياله جيب الخلف | False |  |  |  | 15 | 0.0 |
| 17 | فلتات الجيب الخلف | True | O | 1 | 1 | 15 | 0.0 |
| 18 | plit wist | True | O | 1 | 1 | 15 | 90.0 |
| 19 | بطانه جيب الخلف | True | F | 1 | 1 | 15 | 90.0 |
| 20 |  | False |  |  |  | 0 | None |

## Marker
```
{
 "sbinfo": {
  "USER": "Borham11",
  "WIDTH": "1430",
  "LENGTH": "2930",
  "EFFCNCY": "83.86",
  "USDAREA": "3.51",
  "BOUNDRY": "40.59",
  "PIECES": "9",
  "BUNDLES": "2",
  "CRTIME": "04.03.2025  13:20",
  "MODEL": "PANTS Black.mdl",
  "MATERIALO": "upper fabric",
  "LAYTYPE": "0",
  "BDLTYPE": "1",
  "PCSTOTAL": "28",
  "PCSUNPLC": "0",
  "ANAFILE": "E:\\autonester-new\\Neay blue pants-44.ana"
 },
 "placements": 28,
 "validation": "valid: 28 placements, no overlap/out-of-bounds/orientation issues",
 "computed_efficiency_pct": 83.864,
 "computed_area_m2": 3.5137,
 "computed_length_mm": 2929.93,
 "header": {
  "header_width": 1430.0,
  "header_length": 2929.929931640625,
  "header_eff": 0.8386411070823669,
  "records": 28,
  "bbox_mismatch": [],
  "area_mismatch": []
 }
}
```
