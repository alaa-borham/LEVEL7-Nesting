"""HP-GL / PLT writer and reader.

Scale: ``units_per_mm`` device units per millimetre. HP-GL plotter units are
0.025 mm (40 per mm) — the default here. Nothing else is scaled: a 1000 mm line is
written as 40000 units, and the reader converts back with the same configuration
(verified by tests/test_export_plt.py).

Pen assignment separates tool paths: by default only CUT is pen 1. SEAM/INTERNAL/
GRAIN are drawn with other pens (or excluded) and TEXT is emitted with LB (label)
so it can never become a cut path.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .scene import Scene


@dataclass
class PlotterConfig:
    name: str = "generic HP-GL (0.025 mm units)"
    units_per_mm: float = 40.0
    origin: str = "lower_left"          # lower_left: marker (0,0) -> device (0,0)
    swap_xy: bool = False               # True: marker length runs along device Y
    flip_x: bool = False
    flip_y: bool = False
    pens: dict = field(default_factory=lambda: {"CUT": 1, "NOTCH": 4, "SEAM": 2, "INTERNAL": 2, "GRAIN": 3,
                                                 "TEXT": 3, "PIECE_NAME": 3, "MARK": 3, "BORDER": 0})
    include_text: bool = True
    text_height_mm: float = 10.0
    max_abs_coord: int = 2 ** 30
    terminator: str = "\x03"
    verified_with_device: bool = False  # set True only after a 1:1 test cut on the real plotter

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(**json.load(fh))


class ExportError(Exception):
    pass


def _dev(cfg: PlotterConfig, x: float, y: float, extent) -> tuple[int, int]:
    if cfg.swap_xy:
        x, y = y, x
    if cfg.flip_x:
        x = (extent[2] if not cfg.swap_xy else extent[3]) - x
    if cfg.flip_y:
        y = (extent[3] if not cfg.swap_xy else extent[2]) - y
    return int(round(x * cfg.units_per_mm)), int(round(y * cfg.units_per_mm))


def write_plt(scene: Scene, path: str, cfg: PlotterConfig | None = None) -> dict:
    cfg = cfg or PlotterConfig()
    ext = scene.extent()
    if ext[0] < -1e-6 or ext[1] < -1e-6:
        raise ExportError(f"negative marker coordinates {ext[:2]}; expected origin at lower-left")
    out = ["IN;", "PA;"]
    cur_pen = None
    stats = {"paths": 0, "labels": 0, "by_pen": {}}
    order = sorted(scene.paths, key=lambda p: (cfg.pens.get(p.layer, 0) != 1, cfg.pens.get(p.layer, 0)))
    for p in order:
        pen = cfg.pens.get(p.layer, 0)
        if pen <= 0 or len(p.points) < 2:
            continue
        pts = list(p.points)
        if p.closed and pts[0] != pts[-1]:
            pts.append(pts[0])
        dev = [_dev(cfg, x, y, ext) for x, y in pts]
        for dx, dy in dev:
            if abs(dx) > cfg.max_abs_coord or abs(dy) > cfg.max_abs_coord:
                raise ExportError(f"coordinate {dx},{dy} exceeds device range")
        if p.closed and dev[0] != dev[-1]:
            raise ExportError("closed path not closed after quantisation")
        if pen != cur_pen:
            out.append(f"SP{pen};")
            cur_pen = pen
        out.append(f"PU{dev[0][0]},{dev[0][1]};")
        out.append("PD" + ",".join(f"{x},{y}" for x, y in dev[1:]) + ";")
        out.append("PU;")
        stats["paths"] += 1
        stats["by_pen"][pen] = stats["by_pen"].get(pen, 0) + 1
    if cfg.include_text:
        tpen = cfg.pens.get("TEXT", 0)
        if tpen > 0 and scene.texts:
            out.append(f"SP{tpen};")
            h_cm = cfg.text_height_mm / 10.0
            out.append(f"SI{h_cm * 0.7:.3f},{h_cm:.3f};")
            for t in scene.texts:
                x, y = _dev(cfg, t.position[0], t.position[1], ext)
                safe = t.text.encode("ascii", "replace").decode("ascii").replace(cfg.terminator, "?")
                out.append(f"PU{x},{y};LB{safe}{cfg.terminator}")
                stats["labels"] += 1
    out.append("PU;SP0;")
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    stats["units_per_mm"] = cfg.units_per_mm
    return stats


@dataclass
class PltPath:
    pen: int
    points: list[tuple[float, float]]


def read_plt(path: str, cfg: PlotterConfig | None = None) -> tuple[list[PltPath], list[tuple[int, str]]]:
    """Minimal HP-GL reader (IN, PA, SP, PU, PD, SI, LB) for verification. Returns mm."""
    cfg = cfg or PlotterConfig()
    data = open(path, encoding="ascii").read()
    paths: list[PltPath] = []
    labels: list[tuple[int, str]] = []
    pen = 0
    cur: list[tuple[float, float]] | None = None
    pos = (0, 0)
    i = 0
    term = cfg.terminator
    while i < len(data):
        if data[i] in " \r\n;":
            i += 1
            continue
        cmd = data[i:i + 2]
        i += 2
        if cmd == "LB":
            j = data.index(term, i)
            labels.append((pen, data[i:j]))
            i = j + 1
            continue
        j = data.find(";", i)
        j = len(data) if j < 0 else j
        args = [int(v) for v in re.findall(r"-?\d+", data[i:j])] if cmd in ("PU", "PD", "SP") else []
        i = j + 1
        if cmd == "SP":
            pen = args[0] if args else 0
        elif cmd == "PU":
            if cur and len(cur) > 1:
                paths.append(PltPath(pen, cur))
            cur = None
            if args:
                pos = (args[-2], args[-1])
        elif cmd == "PD":
            if cur is None:
                cur = [(pos[0] / cfg.units_per_mm, pos[1] / cfg.units_per_mm)]
            for k in range(0, len(args) - 1, 2):
                pos = (args[k], args[k + 1])
                cur.append((pos[0] / cfg.units_per_mm, pos[1] / cfg.units_per_mm))
    if cur and len(cur) > 1:
        paths.append(PltPath(pen, cur))
    return paths, labels
