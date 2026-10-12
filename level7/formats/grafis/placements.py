"""Marker placement block (2, 8, 0, 0) — present in SCB files only.

Header (96 bytes): bytes 32..40 = u32 ?, f32 WIDTH; bytes 56..64 = u32 PCSTOTAL,
u32 number of GRDTAB entries; bytes 72..80 = f32 efficiency (ratio), f32 LENGTH;
bytes 80..88 = u16 ?, u16 GRDTAB count, u16 ?, u16 number of part records.
Then PCSTOTAL records of 120 bytes:

    +0   u16 part number           confirmed (matches #SBTLIST)
    +2   u16 GRDTAB size index     confirmed (10 = "44" for the 44 marker)
    +4   f32 width, height         confirmed: bbox size of the cut contour
    +12  f32 xmin, ymin            confirmed: bbox origin of the cut contour (pattern coords)
    +20  f32 X, Y                  confirmed: lower-left of the placed bbox in the marker
    +28  f32 unknown (+0.0/-0.0)
    +32  f32 unknown (0)
    +36  f32 base rotation (deg)   probable (-90 or -360)
    +40  u8  flags                 0x80 => +180 deg (probable; == bundle 2 in sample), 0x40 unknown
    +41  u8  mirror                probable: 1 on second copy of every count=1/mirror=1 part
    +42  u16 running number
    +44  f32 area (m^2)            confirmed: equals cut contour area
    +56  u32 record number 1..N
    +64  f32,f32 unknown point
    +84  f32 additional rotation (0/180 deg)  probable
    +88  u16 copy number, u16 bundle  confirmed (bundle 1/2 matches #SBGRLST)

Placement transform (reproduces the marker with zero overlap and exactly the
EFFCNCY/USDAREA/LENGTH/WIDTH stored by GRAFIS):
    p' = Rot(base + extra + (180 if flags & 0x80)) * MirrorX^(mirror) * p
    then translate so that bbox(p') lower-left == (X, Y)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

REC = 120
HDR = 96


@dataclass
class PlacementRecord:
    part: int
    size_index: int
    bbox_w: float
    bbox_h: float
    xmin: float
    ymin: float
    x: float
    y: float
    base_rot: float
    flags: int
    mirror: bool
    area_m2: float
    seq: int
    extra_rot: float
    copy: int
    bundle: int
    raw: bytes

    @property
    def rotation(self) -> float:
        r = self.base_rot + self.extra_rot + (180.0 if self.flags & 0x80 else 0.0)
        return r % 360.0


@dataclass
class MarkerHeader:
    width: float
    length: float
    efficiency: float
    pieces_total: int
    grd_count: int
    raw: bytes


def decode_marker(payload: bytes, expected: int | None = None) -> tuple[MarkerHeader, list[PlacementRecord], list[str]]:
    errors = []
    if len(payload) < HDR:
        raise ValueError("marker block too short")
    width = struct.unpack_from("<f", payload, 36)[0]
    total, grd = struct.unpack_from("<II", payload, 56)
    eff, length = struct.unpack_from("<ff", payload, 72)
    hdr = MarkerHeader(width, length, eff, total, grd, payload[:HDR])
    n = total if expected is None else expected
    recs = []
    for k in range(n):
        o = HDR + REC * k
        if o + REC > len(payload):
            errors.append(f"placement record {k} exceeds block")
            break
        r = payload[o:o + REC]
        part, size = struct.unpack_from("<HH", r, 0)
        w, h, xmin, ymin, x, y = struct.unpack_from("<6f", r, 4)
        base = struct.unpack_from("<f", r, 36)[0]
        flags, mir, seq = r[40], r[41], struct.unpack_from("<H", r, 42)[0]
        area = struct.unpack_from("<f", r, 44)[0]
        extra = struct.unpack_from("<f", r, 84)[0]
        copy, bundle = struct.unpack_from("<HH", r, 88)
        recs.append(PlacementRecord(part, size, w, h, xmin, ymin, x, y, base, flags, bool(mir), area, seq,
                                    extra, copy, bundle, bytes(r)))
    return hdr, recs, errors
