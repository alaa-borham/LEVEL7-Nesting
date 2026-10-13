# GRAFIS model / marker file format — what is understood

Evidence base: `samples/Neay blue pants.mdl` (2,003,864 B, SHA-256 `0b729b22…fc51`),
`samples/Neay blue pants-44.scb` (1,097,872 B, SHA-256 `a96d5513…0f4c`, 1430 mm) and
`samples/Neay blue pants-44-1500.scb` (1,111,088 B, 1500 mm, signature variant `VD`), plus GRAFIS
screenshots of both markers (`docs/evidence/`). Everything below was
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
| 8 | bytes | `GRAFIS-Modelldatei` + 2-letter variant (`VB` in the first two files, `VD` in the 1500 marker) + `\n\0\n\0`, zero padding to 80; the variant's meaning is U, the structure is identical | C |
| 80… | blocks | block chain | C |
| end−8 | bytes | `mdlEND_5` | C |

Block: `u32 check (C, see below)`, `u32 length in 8-byte units (from block start)`, `"BLO5kenn"`,
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
* kind 4: text. Words: (x0,y0) = text-frame origin (top-left), (x1,y1) opposite bbox corner; (w, height h);
  (0, 0.4); f32 angle in **radians** at +32; text string at +48. GRAFIS inserts the text at
  origin + R(angle)·(5, −(h+5)) (frame = h + 2×5 mm); on mirrored copies at origin + R(angle)·(5, −5) turned
  180° (C: identical in all 15 sizes of the piece DXF exports and in the 44/1500 marker DXF).
* kind 6: position = degenerate bbox (C), value text (e.g. "221", "I=342", "300 (2*)"), sub-lines (cross/square) — **measurement annotation (C)**:
  every value equals the #TFLIST measurement of the same size (615/615 in the sample MDL).
* style: `0` = cut line — written by GRAFIS into the SCB for the nested size only (C);
  `-7` seam line (C, = GRAFIS DXF layer 8); `-6` net contour lying on the cut line, not exported as
  seam (C); `-3` grain arrow (C: identical to GRAFIS' piece DXF exports in all 15 grading entries); `1` other lines.
* notches: flag-2, 2-point, 5 mm style-1 elements. If one end lies on the cut contour it is a cut
  notch (base on the contour, pointing inward) — 44/44 identical to the notch slits in GRAFIS' DXF;
  if it lies on the seam line it is a seam notch (GRAFIS layer 8) — 24/24 identical (C, size 44).
  GRAFIS additionally writes a 6.7 mm slit at the hem notch of the two bundle-2 front copies only (U).
* Coordinates are millimetres (P, strong): `#TFLIST` units mm; front hem line at y = −1040 =
  T2M4/T5M4 (size 44); SCB WIDTH equals max Y of the reconstructed marker.
* Curves are stored as evaluated polylines; spline parameters are not read (unsupported).

### Cut contour in MDL (C — verified in all sizes)
GRAFIS' AAMA export (`samples/reference/aama`): all 165 grade points of the 11 production pieces, graded by
the RUL deltas into the 14 sizes, lie on LEVEL7's contours within 0.007 mm (RUL has 2 decimals). The AAMA
"sample size 40" is GRAFIS' base `__HN40_0` (geometry identical to size 28 in this model).

MDL has no cut flags. The reader takes the largest closed cycle formed by whole polyline elements
joined end-to-end. For size 44 this selects exactly GRAFIS' cut-flag id set for 9/9 placed parts; the
same id set is selected in all 15 grading entries; area and bbox equal GRAFIS' stored values.

## 4. Marker placement block (2,8,0,0) — SCB (C/P)

Header: f32 WIDTH @36, u32 PCSTOTAL @56, u32 GRDTAB count @60, f32 efficiency ratio @72,
f32 exact LENGTH @76. Then PCSTOTAL records × 120 B from offset 96 — see
`level7/formats/grafis/placements.py` for the field table.

Transform (C; reproduces the marker with zero overlap, all grain lines parallel to the length,
efficiency 83.86 %, area 3.51 m², length 2929.93 = GRAFIS values, and is visually identical — piece
positions, orientation, left/right and bundle A/B — to the GRAFIS screen view,
`docs/evidence/grafis_original_1430.png` vs `docs/evidence/level7_reconstruction_1430.png`):
`rotation = base(+36) + extra(+84) + 180·(flags@40 & 0x80)`, `mirror = byte@41`, mirror = x→−x before
rotation, then translate so that the bbox lower-left equals (X,Y)@20.

Second layout (1500 mm marker): the same rules reproduce it unchanged — zero overlap, grain parallel,
efficiency 82.197 % (EFFCNCY 82.19), area 3.51 m², U/B 1.42 m, and identical to the GRAFIS screen view
(`docs/evidence/grafis_new_1500.png` vs `level7_reconstruction_1500.png`). It contains rotation/mirror
combinations absent from the first marker. Computed length 2849.86 vs stored 2849.93 mm (0.065 mm).
Flag 0x40 occurs with and without rotation → still U.

Reference DXF (`samples/reference/44-150.dxf`, GRAFIS export of the 1500 marker, R12, one block per
piece, layer 1 = cut with notch spikes, layer 8 = seam + texts): all 28 cut contours equal LEVEL7's
reconstruction from the SCB within 0.0008 mm; notches, seam lines and texts as described above
(`tests/test_grafis_reference_dxf.py`).

`EFFCNCY` = Σ placed cut areas / (WIDTH × LENGTH) (C).

Open points (U): placement fields +28, +64..72, flag bit 0x40, blocks (2,4..9)
except (2,8), construction blocks (3,k,1..6). Bundle 1 = "A", bundle 2 = "B" in the GRAFIS view (C).
GRAFIS "U/B" = marker length / number of bundles (1.46 m, C).


## Differences between GRAFIS versions (see GRAFIS_RELEASES.md)
* Signature variants seen: VB, VD (earlier files), VA (GRAFIS 26 files, 10/2026). Unknown variants are read
  block by block and reported as "COMPAT:" notes.
* #TLIST: flag "*" (MDL, older SCB) or ">" (GRAFIS 26 SCB); GRAFIS 26 SCBs append ` V="<model path>"` after
  the ID. MDL name column: the two numbers may run together when wide ("basic 2381152").
* #GRDTAB: older files list the base entry ("__HN40_0") first and the sizes reference it ("28 => __HN40_0");
  GRAFIS 26 SCBs list all entries alphabetically without references ("2XL" … "XS", "__HN44_0"). The base entry
  is recognised by its "__" name; a size whose reference is the base entry uses the base geometry.
* Lines of #TLIST / #GRDTAB / #SBTLIST in an unknown layout are no longer dropped silently: they are reported as
  "COMPAT:" notes, the GUI warns and offers a compatibility report (Help menu).


## Check values (C)
The u32 at file offset 0 (over the 80-byte header) and the first u32 of every block (over the whole block)
are check values that GRAFIS verifies — a stale value makes GRAFIS report "Style cannot be read (GRAFIS installed
incorrectly, computer error or corrupt file)". Algorithm (level7.formats.grafis.container.grafis_check), with the
check field itself set to 0: read the bytes as signed 16-bit little-endian words; acc += k * word for k = 1, 2, …;
whenever acc >= 1,024,000,000 subtract 1,024,000,000; acc is a 32-bit signed integer (wraps around).
Reproduces all 5 file headers and 3150 of 3159 blocks of the sample files; the 9 others are piece-geometry blocks
of more than 32k words, which LEVEL7 never rewrites (the SCB writer refuses to write a block whose original check
value it cannot reproduce).
