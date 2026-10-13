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
from pathlib import Path

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
    dialect: str = "hpgl"               # "hpgl": SP/PU/PD with ';'   "grafis": one command per CRLF line, PA/PD/PU
    text_mode: str = "label"            # "label" (HP-GL LB) | "strokes" (vector font) | "none"
    text_layers: list = field(default_factory=lambda: ["TEXT", "PIECE_NAME"])
    merge_notches: bool = False         # put notch slits into the cut contour as there-and-back spikes
    line_type: str = "solid"            # "solid": LT (continuous lines)  "lt1": LT1 as in GRAFIS' file (HP-GL
    #                                     line pattern 1 = dotted on plotters that honour it)

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


def algotex_grafis_config() -> PlotterConfig:
    """Profile reproducing GRAFIS' PLT output for the Algotex device (reference file
    samples/reference/Neay blue pants-44-1500.plt, GRAFIS plot options: 1:1, piece annotation,
    other text, seam lines, all symbols; grain line off). File-level equivalence is tested; a
    physical test cut is still required before setting ``verified_with_device``."""
    return PlotterConfig(name="Algotex (GRAFIS-compatible PLT)", dialect="grafis", text_mode="strokes",
                         text_layers=["TEXT"], merge_notches=True,
                         pens={"CUT": 1, "NOTCH": 1, "SEAM": 1, "TEXT": 1, "INTERNAL": 0, "GRAIN": 0,
                               "PIECE_NAME": 0, "MARK": 0, "BORDER": 0})


PRESETS = {"generic": PlotterConfig, "algotex_grafis": algotex_grafis_config}


def merge_spikes(points, spikes, closed=True, tol=0.01):
    """Insert (base, tip) spikes into a polyline at the base point: ... base, tip, base ..."""
    import math
    pts = list(points)
    for base, tip in spikes:
        best = None
        n = len(pts)
        segs = range(n if closed else n - 1)
        for i in segs:
            a, b = pts[i], pts[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((base[0] - a[0]) * dx + (base[1] - a[1]) * dy) / L2))
            q = (a[0] + t * dx, a[1] + t * dy)
            d = math.dist(q, base)
            if best is None or d < best[0]:
                best = (d, i, t)
        if best is None or best[0] > tol:
            continue
        _, i, t = best
        if t <= 1e-9:
            pts[i:i + 1] = [pts[i], tip, pts[i]]
        elif t >= 1 - 1e-9:
            j = (i + 1) % n
            pts[j:j + 1] = [pts[j], tip, pts[j]]
        else:
            pts[i + 1:i + 1] = [base, tip, base]
    return pts


def write_plt(scene: Scene, path: str, cfg: PlotterConfig | None = None) -> dict:
    from .strokefont import text_strokes, unsupported_chars
    cfg = cfg or PlotterConfig()
    ext = scene.extent()
    if ext[0] < -1e-6 or ext[1] < -1e-6:
        raise ExportError(f"negative marker coordinates {ext[:2]}; expected origin at lower-left")
    grafis = cfg.dialect == "grafis"
    lt = "LT1" if cfg.line_type == "lt1" else "LT"
    out = ["IN", lt] if grafis else ["IN;", f"{lt};", "PA;"]
    cur_pen = None
    stats = {"paths": 0, "labels": 0, "text_strokes": 0, "by_pen": {}, "skipped_chars": set(), "notches_merged": 0}
    paths = list(scene.paths)
    if cfg.merge_notches:
        notches: dict = {}
        for p in paths:
            if p.layer == "NOTCH" and len(p.points) == 2 and cfg.pens.get("NOTCH", 0) > 0:
                notches.setdefault(p.owner, []).append((p.points[0], p.points[1]))
        # seam notch marks (2-point seam paths touching another seam path of the same piece) -> spikes
        import math as _m
        seam_by_owner: dict = {}
        for p in paths:
            if p.layer == "SEAM" and cfg.pens.get("SEAM", 0) > 0:
                seam_by_owner.setdefault(p.owner, []).append(p)
        seam_marks: dict = {}
        mark_ids = set()
        for owner, sp in seam_by_owner.items():
            lines = [q for q in sp if not (len(q.points) == 2 and _m.dist(*q.points) < 10)]
            for q in sp:
                if q in lines:
                    continue
                for ln in lines:
                    pts = ln.points + ([ln.points[0]] if ln.closed else [])
                    from shapely.geometry import LineString as _LS, Point as _P
                    L = _LS(pts)
                    a, b = q.points
                    if L.distance(_P(a)) <= 0.01 or L.distance(_P(b)) <= 0.01:
                        base, tip = (a, b) if L.distance(_P(a)) <= L.distance(_P(b)) else (b, a)
                        seam_marks.setdefault(id(ln), []).append((base, tip))
                        mark_ids.add(id(q))
                        break
        merged = []
        for p in paths:
            if p.layer == "NOTCH" or id(p) in mark_ids:
                continue
            if p.layer == "SEAM" and id(p) in seam_marks:
                from .scene import Path as SPath
                p = SPath(p.layer, merge_spikes(p.points, seam_marks[id(p)], closed=p.closed), p.closed, p.owner)
            if p.layer == "CUT" and p.owner in notches:
                from .scene import Path as SPath
                pts = merge_spikes(p.points, notches[p.owner], closed=True)
                stats["notches_merged"] += len(notches[p.owner])
                p = SPath(p.layer, pts, True, p.owner)
            merged.append(p)
        paths = merged
    if cfg.text_mode == "strokes":
        from .scene import Path as SPath
        tpen = cfg.pens.get("TEXT", 0)
        for t in scene.texts:
            if t.layer not in cfg.text_layers or tpen <= 0:
                continue
            stats["skipped_chars"] |= unsupported_chars(t.text)
            for st in text_strokes(t.text, t.position, t.height, t.rotation):
                if len(st) >= 2:
                    paths.append(SPath("TEXT", st, False, t.owner))
                    stats["text_strokes"] += 1
    order = sorted(paths, key=lambda p: (cfg.pens.get(p.layer, 0) != 1, cfg.pens.get(p.layer, 0)))
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
        if grafis:
            out.append(f"PA{dev[0][0]},{dev[0][1]}")
            out.append("PD")
            out += [f"PA{x},{y}" for x, y in dev[1:]]
            out.append("PU")
        else:
            if pen != cur_pen:
                out.append(f"SP{pen};")
                cur_pen = pen
            out.append(f"PU{dev[0][0]},{dev[0][1]};")
            out.append("PD" + ",".join(f"{x},{y}" for x, y in dev[1:]) + ";")
            out.append("PU;")
        stats["paths"] += 1
        stats["by_pen"][pen] = stats["by_pen"].get(pen, 0) + 1
    if cfg.include_text and cfg.text_mode == "label":
        tpen = cfg.pens.get("TEXT", 0)
        texts = [t for t in scene.texts if t.layer in cfg.text_layers]
        if tpen > 0 and texts:
            out.append(f"SP{tpen};")
            h_cm = cfg.text_height_mm / 10.0
            out.append(f"SI{h_cm * 0.7:.3f},{h_cm:.3f};")
            for t in texts:
                x, y = _dev(cfg, t.position[0], t.position[1], ext)
                safe = t.text.encode("ascii", "replace").decode("ascii").replace(cfg.terminator, "?")
                out.append(f"PU{x},{y};LB{safe}{cfg.terminator}")
                stats["labels"] += 1
    if grafis:
        out.append("PG")
        newline = "\r\n"
    else:
        out.append("PU;SP0;")
        newline = "\n"
    with open(path, "w", encoding="ascii", newline="") as fh:
        fh.write(newline.join(out) + newline)
    stats["units_per_mm"] = cfg.units_per_mm
    stats["skipped_chars"] = sorted(stats["skipped_chars"])
    return stats


@dataclass
class PltPath:
    pen: int
    points: list[tuple[float, float]]


def read_plt(path: str, cfg: PlotterConfig | None = None) -> tuple[list[PltPath], list[tuple[int, str]]]:
    """HP-GL reader for verification (IN, PA, SP, PU, PD, SI, LB, LT, PG; ';' or newline separated).
    Coordinates are returned in mm."""
    cfg = cfg or PlotterConfig()
    data = Path(path).read_text(encoding="ascii")
    paths: list[PltPath] = []
    labels: list[tuple[int, str]] = []
    pen, down, cur, pos = 1, False, None, (0, 0)
    u = cfg.units_per_mm
    i, n = 0, len(data)

    def flush():
        nonlocal cur
        if cur and len(cur) > 1:
            paths.append(PltPath(pen, cur))
        cur = None
    while i < n:
        ch = data[i]
        if not ch.isalpha():
            i += 1
            continue
        cmd = data[i:i + 2].upper()
        i += 2
        if cmd == "LB":
            j = data.find(cfg.terminator, i)
            j = n if j < 0 else j
            labels.append((pen, data[i:j]))
            i = j + 1
            continue
        j = i
        while j < n and not data[j].isalpha():
            j += 1
        nums = [int(float(v)) for v in re.findall(r"-?\d+(?:\.\d+)?", data[i:j])]
        i = j
        if cmd == "SP":
            flush()
            pen = nums[0] if nums else 0
            down = False
        elif cmd in ("PU", "PD"):
            if cmd == "PU":
                flush()
                down = False
            else:
                down = True
                cur = cur or [(pos[0] / u, pos[1] / u)]
            for k in range(0, len(nums) - 1, 2):
                pos = (nums[k], nums[k + 1])
                if down:
                    cur.append((pos[0] / u, pos[1] / u))
        elif cmd == "PA":
            for k in range(0, len(nums) - 1, 2):
                pos = (nums[k], nums[k + 1])
                if down:
                    cur.append((pos[0] / u, pos[1] / u))
        elif cmd in ("IN", "PG"):
            flush()
            down = False
    flush()
    return paths, labels
