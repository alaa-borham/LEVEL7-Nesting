# Inspection report: Neay blue pants.mdl

- size: 2,003,864 bytes
- SHA-256: `0b729b223c72caa8685734b430c83e35009b1b4d151cacaa343edf8b8a78fc51`
- signature: `GRAFIS-ModelldateiVB`
- blocks: 558
- structural errors: none

## Confirmed
- block chain: 558 blocks follow each other exactly via the length field (u32 units of 8 bytes) from offset 80 to the 'mdlEND_5' trailer; header u32[1]*8+8 == file size
- text sections in block (2,1,0,0), CRLF lines; #VERSION text = '1000' (meaning not known; not treated as GRAFIS program version)
- geometry blocks (3,part,7,size): 4155/4155 polyline elements decode to points whose bounding box equals the bbox stored in the element record

## Probable interpretations
- text encoding cp1256: Arabic part names decode to valid words
- cut contour (MDL) = largest closed cycle of whole polyline elements; matches the GRAFIS cut flags of the 44 marker for 9/9 placed parts and the same element set is chosen in all 15 grading entries
- units = millimetres: '#TFLIST' tables declare mm; part 7 size 44 has its hem line at y=-1040 and T2M4/T5M4 = 1040 for size 44; SCB WIDTH 1430 equals the max Y of the reconstructed marker; front length ~1135 is realistic only in mm
- style -7/-6 = seam (net) line, -3 = grain line, 2-point flagged style 1 = notch

## Unknown
- header u32[0] and per-block u32 check value: not a byte sum, CRC-32 or Adler-32
- symbol elements (kind 6): position and code text read; meaning (drill hole, reference mark, ...) unknown -> exported only on layer MARK
- construction data blocks (3,k,2..6) are not interpreted; only evaluated geometry

## Unsupported
- writing MDL/SCB files
- curve definitions: GRAFIS stores evaluated polylines; original spline parameters are not read

## Text sections
- `#VERSION` at file offset 184, 1 lines
- `#GRDTAB` at file offset 200, 15 lines
- `#TLIST` at file offset 721, 19 lines
- `#TFLIST002` at file offset 2135, 6 lines
- `#TFLIST004` at file offset 2977, 13 lines
- `#TFLIST005` at file offset 4925, 6 lines
- `#TFLIST007` at file offset 5767, 7 lines
- `#TFLIST008` at file offset 6767, 7 lines
- `#TFLIST009` at file offset 7767, 6 lines
- `#TFLIST012` at file offset 8609, 5 lines
- `#TFLIST013` at file offset 9293, 5 lines
- `#TFLIST014` at file offset 9977, 3 lines
- `#TFLIST018` at file offset 10345, 3 lines
- `#BFLIST001` at file offset 10713, 9 lines
- `#ENDINFO` at file offset 11976, 1 lines

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
