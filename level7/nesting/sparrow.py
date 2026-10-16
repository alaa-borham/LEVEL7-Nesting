"""Optional high-performance engine: sparrow (J. Gardeyn, KU Leuven; MIT licence; uses jagua-rs, MPL-2.0).

sparrow solves irregular strip packing by overlap minimisation and strip compression. LEVEL7 runs the
bundled executable (engines/sparrow[.exe]) as a separate process:

* input: one item type per (piece, size, mirrored) with the exact cut contour (mirror already applied),
  its allowed rotations (grain) and demand; strip height = usable fabric width; min separation = spacing.
* optional warm start: a valid layout from LEVEL7's own engine, so sparrow starts from it and only
  compresses further.
* progress: feasible intermediate solutions are read from the SVG snapshots sparrow writes
  (``<n>_<length>_{expl_f|cmpr|final}.svg``); "stop" kills the process and keeps the best snapshot.

Pieces are only translated and rotated by the allowed angles (never reshaped; scaled only by the shrinkage
set on the fabric); every returned layout is checked again by LEVEL7's validator in the service layer.

Shrinkage and directional buffers act in marker axes, so for them each item type is given to sparrow already
turned to its first allowed rotation, scaled and grown by the buffer rectangle; the remaining allowed turns
keep only the turns that commute with it: all of them when shrinkage and buffer are the same in X and Y,
otherwise 0 / 180° (the 90° turns are then left to LEVEL7's own engine; the shorter valid layout wins).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from shapely.geometry import Polygon

from ..geometry import grow_rect, ring_area, transform_points
from ..model import Placement
from .engine import NestItem, NestResult

FEASIBLE = ("expl_f", "cmpr", "final")
_USE = re.compile(r'<use href="#item_\d+_(\d+)" transform="translate\(([-\d.eE+]+)[ ,]+([-\d.eE+]+)\),?\s*'
                  r'rotate\(([-\d.eE+]+)\)"')


def _nice():
    try:
        os.nice(5)
    except OSError:
        pass


def find_binary() -> str | None:
    exe = "sparrow.exe" if os.name == "nt" else "sparrow"
    cands = [os.environ.get("LEVEL7_SPARROW", "")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(os.path.join(base, "engines", exe))
        cands.append(os.path.join(os.path.dirname(sys.executable), "engines", exe))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cands.append(os.path.join(root, "engines", exe))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def available() -> bool:
    return find_binary() is not None


def _groups(items: list[NestItem]):
    g: dict = {}
    for it in items:
        g.setdefault((it.shape_key, tuple(it.rotations)), []).append(it)
    return list(g.values())


def _frame(fabric):
    """(ex, ey, sx, sy, marker_axes): buffer half-widths, shrink factors, whether shapes go in marker axes."""
    ex, ey = max(0.0, fabric.buffer_x) / 2.0, max(0.0, fabric.buffer_y) / 2.0
    sx, sy = fabric.scale
    return ex, ey, sx, sy, bool(ex or ey or sx != 1.0 or sy != 1.0)


def _base_rot(its, fabric) -> float:
    return its[0].rotations[0] if _frame(fabric)[4] else 0.0


def _rel_angles(its, fabric) -> list[float]:
    """Allowed turns relative to the base rotation that sparrow may use for this item type."""
    ex, ey, sx, sy, axes = _frame(fabric)
    r0 = _base_rot(its, fabric)
    rel = [round((r - r0) % 360.0, 6) for r in its[0].rotations]
    if axes and not (abs(sx - sy) < 1e-12 and abs(ex - ey) < 1e-12):
        rel = [r for r in rel if r in (0.0, 180.0)]   # 90° turns would swap the X / Y shrinkage and buffers
    return rel


def build_instance(items: list[NestItem], fabric, name="level7") -> tuple[dict, list]:
    groups = _groups(items)
    ex, ey, sx, sy, axes = _frame(fabric)
    out = []
    for k, its in enumerate(groups):
        r0 = _base_rot(its, fabric)
        rel = _rel_angles(its, fabric)
        pts = transform_points(its[0].cut, r0, its[0].mirrored, sx=sx, sy=sy)
        if ex or ey:
            pts = list(grow_rect(Polygon(pts).buffer(0), ex, ey).exterior.coords)[:-1]
        if ring_area(pts) < 0:
            pts = pts[::-1]
        data = [[float(x), float(y)] for x, y in pts] + [[float(pts[0][0]), float(pts[0][1])]]
        out.append({"id": k, "demand": len(its),
                    "orientation": {"rotation": {"mode": "discrete", "angles": [float(r) for r in rel]}},
                    "shape": {"type": "simple_polygon", "data": data}})
    inst = {"name": name, "items": out, "strip_height": float(fabric.usable_width + 2 * ey)}
    if fabric.spacing > 0:
        inst["min_item_separation"] = float(fabric.spacing)
    return inst, groups


def warm_solution(inst: dict, groups: list, result: NestResult, fabric) -> dict | None:
    """sparrow solution JSON from a LEVEL7 layout (all copies placed), for warm starting."""
    if result is None or result.unplaced:
        return None
    by_uid = {it.uid: k for k, its in enumerate(groups) for it in its}
    placed = []
    for pl in result.placements:
        k = by_uid.get(pl.uid)
        if k is None:
            return None
        ex, ey = _frame(fabric)[:2]
        rel = round((pl.rotation - _base_rot(groups[k], fabric)) % 360.0, 6)
        if rel not in _rel_angles(groups[k], fabric):
            return None                            # start layout uses a turn sparrow is not given: no warm start
        placed.append({"item_id": k, "transformation": {
            "rotation": float(rel), "translation": [pl.x - fabric.margin_start + ex, pl.y - fabric.margin_left + ey]}})
    sol = dict(inst)
    ex = _frame(fabric)[0]
    sol["solution"] = {"strip_width": float(result.length - fabric.margin_start - fabric.margin_end + 2 * ex),
                       "layout": {"container_id": 0, "placed_items": placed}}
    return sol


def _to_result(entries, groups, fabric, length_strip, seed, elapsed, stopped) -> NestResult | None:
    pools = [list(its) for its in groups]
    ex, ey, sx, sy, _ = _frame(fabric)
    pls = []
    for k, x, y, r in entries:
        if k >= len(pools) or not pools[k]:
            return None
        it = pools[k].pop()
        pls.append(Placement(uid=it.uid, piece_uid=it.piece_uid, size=it.size, bundle=it.bundle,
                             x=x + fabric.margin_start - ex, y=y + fabric.margin_left - ey,
                             rotation=round((r + _base_rot(groups[k], fabric)) % 360.0, 6),
                             mirrored=it.mirrored, sx=sx, sy=sy))
    if any(pools):
        return None
    return NestResult(pls, [], length_strip - 2 * ex + fabric.margin_start + fabric.margin_end, 0, elapsed, seed,
                      stopped, [])


def parse_svg(path, groups, fabric, seed=0, elapsed=0.0, stopped=False) -> NestResult | None:
    m = re.match(r"\d+_([\d.]+)_", os.path.basename(path))
    try:
        txt = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    entries = [(int(a), float(b), float(c), float(d)) for a, b, c, d in _USE.findall(txt)]
    return _to_result(entries, groups, fabric, float(m.group(1)) if m else 0.0, seed, elapsed, stopped)


def parse_json(path, groups, fabric, seed=0, elapsed=0.0) -> NestResult | None:
    try:                                   # a file cut off while sparrow was killed: no result, not an error
        sol = json.loads(Path(path).read_text(encoding="utf-8"))["solution"]
        entries = [(p["item_id"], p["transformation"]["translation"][0], p["transformation"]["translation"][1],
                    p["transformation"]["rotation"]) for p in sol["layout"]["placed_items"]]
        width = float(sol["strip_width"])
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
    return _to_result(entries, groups, fabric, width, seed, elapsed, False)


def run(items: list[NestItem], fabric, settings, time_limit: float, progress=None, stop_event=None,
        warm: NestResult | None = None, workers: int | None = None) -> NestResult | None:
    """Run sparrow; returns its best feasible layout (or None if the engine is missing / failed)."""
    exe = find_binary()
    if exe is None or not items:
        return None
    work = tempfile.mkdtemp(prefix="level7_sparrow_")
    t0 = time.monotonic()
    proc = None
    try:
        inst, groups = build_instance(items, fabric)
        src = warm_solution(inst, groups, warm, fabric) if warm is not None else None
        path = os.path.join(work, "job.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(src or inst, fh)
        workers = workers or max(1, (os.cpu_count() or 2) - 1)
        cmd = [exe, "-i", path, "-t", str(max(1, int(round(time_limit)))), "-s", str(int(settings.seed)),
               "--workers", str(workers)]
        # below normal priority (like LEVEL7's own search processes): the windows stay responsive
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
        proc = subprocess.Popen(cmd, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=flags, preexec_fn=None if os.name == "nt" else _nice)
        sols = os.path.join(work, "output", "sols_level7")
        best, best_len, seen = None, None, set()
        stopped = False

        def halted():
            return stop_event is not None and stop_event.is_set()
        while proc.poll() is None:
            if halted():
                stopped = True
                proc.kill()
                break
            # sparrow may run on past its -t (compression after exploration): our timer is the user's timer -
            # 3 s of grace, then its best snapshot is the result (it was 60 s: 148 s shown for 120 s)
            if time.monotonic() - t0 > time_limit + 3.0:
                proc.kill()
                break
            time.sleep(0.3)
            try:
                names = os.listdir(sols)
            except OSError:
                continue
            new = []
            for n in names:
                if n in seen or not n.endswith(".svg") or not any(n.endswith(f"_{t}.svg") for t in FEASIBLE):
                    continue
                seen.add(n)
                m = re.match(r"\d+_([\d.]+)_", n)
                if m is not None and (best_len is None or float(m.group(1)) < best_len):
                    new.append((float(m.group(1)), n))
            # only the shortest new snapshot is read (reading every one fell behind and kept Stop waiting)
            for length, n in sorted(new)[:3]:
                if halted():
                    break
                r = parse_svg(os.path.join(sols, n), groups, fabric, settings.seed, time.monotonic() - t0)
                if r is not None:
                    best, best_len = r, length
                    if progress:
                        progress({"elapsed": time.monotonic() - t0, "evaluations": len(seen),
                                  "length": r.length, "unplaced": 0, "result": r, "final": False})
                    break
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        final = os.path.join(work, "output", "final_level7.json")
        if not stopped and os.path.isfile(final):
            r = parse_json(final, groups, fabric, settings.seed, time.monotonic() - t0)
            if r is not None and (best is None or r.length <= best.length + 1e-6):
                best = r
        if best is not None:
            best.elapsed = time.monotonic() - t0
            best.stopped = stopped
        return best
    except Exception:
        return None
    finally:
        if proc is not None and proc.poll() is None:      # never leave sparrow running after an error
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        shutil.rmtree(work, ignore_errors=True)
