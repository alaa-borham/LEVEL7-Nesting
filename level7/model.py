"""Unified internal data model. All geometry is stored in millimetres.

Original geometry is kept unchanged (as read). The nesting engine works on separate
search approximations (see level7.geometry.approx) whose tolerance is recorded.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum

Point = tuple[float, float]


class Status(str, Enum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class LayType(str, Enum):
    OPEN = "open"                  # single ply, face up
    FACE_TO_FACE = "face_to_face"  # plies alternate face up / down: each placement yields L+R
    FOLDED = "folded"              # folded at one selvedge: usable width = width/2, each placement yields L+R


@dataclass
class Polyline:
    points: list[Point]
    closed: bool = False
    source_id: str | None = None


@dataclass
class Notch:
    position: Point
    direction: Point | None = None   # unit vector into the piece (if known)
    length: float = 5.0
    source_id: str | None = None


@dataclass
class Drill:
    position: Point
    code: str | None = None
    source_id: str | None = None


@dataclass
class Label:
    text: str
    position: Point                      # insertion point (lower-left of the text)
    height: float = 10.0
    box: tuple | None = None             # (x0, y0, x1, y1) as stored by GRAFIS: (x0,y0) = frame origin (top-left)
    angle: float = 0.0                   # degrees, CCW in pattern coordinates


@dataclass
class PieceGeometry:
    """Geometry of one piece in one size."""
    size: str
    cut: list[Point]                                       # outer cut contour (closed, no repeated point)
    corners: list[Point] = field(default_factory=list)      # junctions between cut-line elements (corners)
    holes: list[list[Point]] = field(default_factory=list)  # internal cut-outs
    seam: list[Polyline] = field(default_factory=list)
    internal: list[Polyline] = field(default_factory=list)
    notches: list[Notch] = field(default_factory=list)
    drills: list[Drill] = field(default_factory=list)      # drill holes (none in the GRAFIS samples)
    measures: list[Label] = field(default_factory=list)    # GRAFIS measurement annotations (symbol kind 6)
    grain: Polyline | None = None                           # grain line as read (None = unknown)
    labels: list[Label] = field(default_factory=list)
    source_unit: str = "mm"
    unit_factor: float = 1.0                                # source unit -> mm
    completeness: dict[str, str] = field(default_factory=dict)  # field -> Status value
    source: str = ""                                        # e.g. "MDL block (3,7,7,10)"


@dataclass
class Piece:
    uid: str
    source_id: str                 # ID=... from TLIST or DXF handle
    number: int | None             # part number in source file
    name: str
    material: str | None = None    # material group (e.g. "O" upper fabric, "F" lining)
    production: bool = True        # False for construction / helper parts
    default_count: int = 1         # copies per garment (non-mirrored)
    default_mirrored: int = 0      # mirrored copies per garment
    sizes: dict[str, PieceGeometry] = field(default_factory=dict)
    allowed_rotations: list[float] = field(default_factory=lambda: [0.0, 180.0])
    allow_mirror: bool = False
    grain_angle: float | None = None   # deg of grain line in pattern coordinates (None = unknown)
    notes: list[str] = field(default_factory=list)

    @staticmethod
    def new_uid() -> str:
        return uuid.uuid4().hex[:12]


@dataclass
class Placement:
    uid: str
    piece_uid: str
    size: str
    bundle: int = 1
    x: float = 0.0                 # translation applied after rotation/mirror (mm)
    y: float = 0.0
    rotation: float = 0.0          # degrees CCW
    mirrored: bool = False         # mirror about pattern Y axis (x -> -x) before rotation
    pinned: bool = False
    placed: bool = True
    reason: str | None = None      # why not placed


@dataclass
class FabricSettings:
    width: float = 1500.0          # total width mm
    margin_left: float = 0.0       # selvedge margins (across width)
    margin_right: float = 0.0
    margin_start: float = 0.0      # along length
    margin_end: float = 0.0
    spacing: float = 0.0           # min distance between cut lines (mm)
    lay_type: LayType = LayType.OPEN
    max_length: float | None = None

    @property
    def usable_width(self) -> float:
        w = self.width - self.margin_left - self.margin_right
        return w / 2.0 if self.lay_type == LayType.FOLDED else w


@dataclass
class NestSettings:
    mode: str = "balanced"         # fast / balanced / long
    time_limit: float = 30.0       # seconds
    seed: int = 1
    allow_rotation_180: bool = True
    allow_rotation_90: bool = False
    allow_mirror: bool = False
    curve_tolerance: float = 0.2   # mm, max deviation of search polygon (outward only)
    attempts: int = 0              # 0 = until time limit
    engine: str = "auto"           # auto: built-in start + sparrow compression when available; builtin: only LEVEL7


@dataclass
class CutOrder:
    size_quantities: dict[str, int] = field(default_factory=dict)   # size -> garments
    piece_counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # piece uid -> (normal, mirrored) per garment
    material: str | None = None


@dataclass
class Marker:
    name: str
    fabric: FabricSettings
    placements: list[Placement] = field(default_factory=list)
    length: float = 0.0
    origin: str = "nested"         # "original" (from SCB) / "nested" / "manual"
    seed: int | None = None
    compute_time: float | None = None
    stats: dict = field(default_factory=dict)


@dataclass
class SourceInfo:
    path: str
    kind: str                      # mdl / scb / dxf
    sha256: str
    size: int
    internal_model_name: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Project:
    name: str = "untitled"
    pieces: list[Piece] = field(default_factory=list)
    size_names: list[str] = field(default_factory=list)
    sources: list[SourceInfo] = field(default_factory=list)
    cut_order: CutOrder = field(default_factory=CutOrder)
    nest_settings: NestSettings = field(default_factory=NestSettings)
    markers: list[Marker] = field(default_factory=list)
    export_configs: dict = field(default_factory=dict)
    reports: dict = field(default_factory=dict)
    sbinfo: dict = field(default_factory=dict)

    def piece(self, uid: str) -> Piece:
        for p in self.pieces:
            if p.uid == uid:
                return p
        raise KeyError(uid)


def to_dict(obj) -> dict:
    return asdict(obj)
