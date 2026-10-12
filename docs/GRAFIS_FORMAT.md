# GRAFIS model / marker file format — what is understood

Evidence base: `samples/Neay blue pants.mdl` (2,003,864 B, SHA-256 `0b729b22…fc51`) and
`samples/Neay blue pants-44.scb` (1,097,872 B, SHA-256 `a96d5513…0f4c`). Everything below was
derived from these two files only; statuses: **C** = confirmed by an independent check,
**P** = probable interpretation, **U** = unknown.

> Note: the brief described a marker `Neay blue pants-28.scb` (1,096,472 B, LENGTH 2173, EFFCNCY 86.81).
> The file actually supplied is `Neay blue pants-44.scb` (size 44, LENGTH 2930, EFFCNCY 83.86). All
> numbers here refer to the supplied file.

## 1. Container (C)

| offset | type | meaning | status |
|---|---|---|---|
| 0 | u32 | unknown (not byte-sum / CRC32 / Adler32) | U |
| 4 | u32 | (file size − 8) / 8 | C (both files) |
| 8 | bytes | `GRAFIS-ModelldateiVB\n\0\n\0`, zero padding to 80 | C |
| 80… | blocks | block chain | C |
| end−8 | bytes | `mdlEND_5` | C |

Block: `u32 check (U)`, `u32 length in 8-byte units (from block start)`, `"BLO5kenn"`,
`4×u32 id (a,b,c,d)`, payload. The parser follows the length chain strictly; the chain covers the
file without gaps (558 blocks MDL, 445 SCB). `BLO5kenn` is never searched for.

Block ids seen: `(1,1,0,0)` header record; `(2,1)` text; `(2,2)` size table (binary);
`(2,4)`, `(2,6)`, `(2,7)` settings (U); `(2,8)` marker placements (SCB only); `(2,9)` marker
environment incl. paths (SCB only, U); `(3,part,1..7,n)` per part — `3` construction objects (MDL only),
`7` evaluated geometry per GRDTAB entry (C), the rest U.

## 2. Text block (2,1,0,0) (C)

CRLF lines, sections `#VERSION` (text `1000`, meaning U), `#GRDTAB` (size table; MDL maps sizes to
`__HN40_0…__HN53_0`), `#TLIST` (parts), `#TFLIST nnn` / `#BFLIST nnn` (measurement tables in mm per
size), SCB additionally `#SBINFO`, `#SBGRLST`, `#SBTLIST`. Arabic names decode as Windows-1256 (P).

`#TLIST` line: `[*] NNN [x] name … [x M cc mm] ID=hex`. Part number NNN = block index `b` in
`(3,b,…)` (C). `x O 01 01` present only on production parts (P); `O`/`F` = material group (P; SCB key
`MATERIALO upper fabric` uses the same `O`); `cc`/`mm` = copies / mirrored copies (P, consistent with
`#SBTLIST` and placements). `ID=` is shared between MDL and SCB for all 19 parts (C).

## 3. Geometry block (3, part, 7, size) (C)

One block per part and GRDTAB entry (15 = base `__HN40_0` + 14 sizes; base geometry equals size 28).

```
u32 nrec, u32 length/8
nrec × 40 B: u32 oid | u32 flag (0/2) | u32 aux ptr | u32 count | u32 data ptr |
             u8 kind (2 polyline, 4 text, 6 symbol) | u8 (=2) | i16 style | 4×f32 bbox
pool: per record in order: [16 B aux if flag==2] + count × 8 B
```

* kind 2: `count` points (f32 x, f32 y). **4155/4155** polylines per file match their stored bbox (C).
* kind 4: two corner points, heights, text (e.g. size "44") (P).
* kind 6: position = degenerate bbox (C), code text (e.g. "221"), sub-lines (cross/square) — meaning U.
* style: `0` = cut line — written by GRAFIS into the SCB for the nested size only (C);
  `-7/-6` seam/net contour (P); `-3` grain arrow (P); `1` other lines; flag-2, 2-point, ~5 mm style-1
  elements = notches (P).
* Coordinates are millimetres (P, strong): `#TFLIST` units mm; front hem line at y = −1040 =
  T2M4/T5M4 (size 44); SCB WIDTH equals max Y of the reconstructed marker.
* Curves are stored as evaluated polylines; spline parameters are not read (unsupported).

### Cut contour in MDL (P, verified)
MDL has no cut flags. The reader takes the largest closed cycle formed by whole polyline elements
joined end-to-end. For size 44 this selects exactly GRAFIS' cut-flag id set for 9/9 placed parts; the
same id set is selected in all 15 grading entries; area and bbox equal GRAFIS' stored values.

## 4. Marker placement block (2,8,0,0) — SCB (C/P)

Header: f32 WIDTH @36, u32 PCSTOTAL @56, u32 GRDTAB count @60, f32 efficiency ratio @72,
f32 exact LENGTH @76. Then PCSTOTAL records × 120 B from offset 96 — see
`level7/formats/grafis/placements.py` for the field table.

Transform (P; reproduces the marker with zero overlap, all grain lines parallel to the length,
efficiency 83.86 %, area 3.51 m², length 2929.93 = GRAFIS values):
`rotation = base(+36) + extra(+84) + 180·(flags@40 & 0x80)`, `mirror = byte@41`, mirror = x→−x before
rotation, then translate so that the bbox lower-left equals (X,Y)@20.

`EFFCNCY` = Σ placed cut areas / (WIDTH × LENGTH) (C).

Open points (U): u32 check values, placement fields +28, +64..72, flag bit 0x40, blocks (2,4..9)
except (2,8), construction blocks (3,k,1..6). Absolute left/right orientation of the marker cannot be
proven without a GRAFIS screenshot (a global vertical flip is indistinguishable).
