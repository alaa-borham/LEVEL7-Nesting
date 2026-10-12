"""Optional high-performance engine: sparrow (J. Gardeyn, KU Leuven; MIT licence; uses jagua-rs, MPL-2.0).

sparrow solves irregular strip packing by overlap minimisation and strip compression. LEVEL7 runs the
bundled executable (engines/sparrow[.exe]) as a separate process:

* input: one item type per (piece, size, mirrored) with the exact cut contour (mirror already applied),
  its allowed rotations (grain) and demand; strip height = usable fabric width; min separation = spacing.
* optional warm start: a valid layout from LEVEL7's own engine, so sparrow starts from it and only
  compresses further.
* progress: feasible intermediate solutions are read from the SVG snapshots sparrow writes
  (``<n>_<length>_{expl_f|cmpr|final}.svg``); "stop" kills the process and keeps the best snapshot.

Pieces are only translated and rotated by the allowed angles (never scaled or reshaped); every returned
layout is checked again by LEVEL7's validator in the service layer.
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

from ..geometry import ring_area, transform_points
from ..model import Placement
from .engine import NestItem, NestResult

FEASIBLE = ("expl_f", "cmpr", "final")
_USE = re.compile(r'<use href="#item_\d+_(\d+)" transform="translate\(([-\d.eE+]+)[ ,]+([-\d.eE+]+)\),?\s*'
                  r'rotate\(([-\d.eE+]+)\)"')


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


def build_instance(items: list[NestItem], fabric, name="level7") -> tuple[dict, list]:
    groups = _groups(items)
    out = []
    for k, its in enumerate(groups):
        pts = transform_points(its[0].cut, 0.0, its[0].mirrored)
        if ring_area(pts) < 0:
            pts = pts[::-1]
        data = [[float(x), float(y)] for x, y in pts] + [[float(pts[0][0]), float(pts[0][1])]]
        out.append({"id": k, "demand": len(its),
                    "orientation": {"rotation": {"mode": "discrete", "angles": [float(r) for r in its[0].rotations]}},
                    "shape": {"type": "simple_polygon", "data": data}})
    inst = {"name": name, "items": out, "strip_height": float(fabric.usable_width)}
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
        placed.append({"item_id": k, "transformation": {
            "rotation": float(pl.rotation), "translation": [pl.x - fabric.margin_start, pl.y - fabric.margin_left]}})
    sol = dict(inst)
    sol["solution"] = {"strip_width": float(result.length - fabric.margin_start - fabric.margin_end),
                       "layout": {"container_id": 0, "placed_items": placed}}
    return sol


def _to_result(entries, groups, fabric, length_strip, seed, elapsed, stopped) -> NestResult | None:
    pools = [list(its) for its in groups]
    pls = []
    for k, x, y, r in entries:
        if k >= len(pools) or not pools[k]:
            return None
        it = pools[k].pop()
        pls.append(Placement(uid=it.uid, piece_uid=it.piece_uid, size=it.size, bundle=it.bundle,
                             x=x + fabric.margin_start, y=y + fabric.margin_left, rotation=r % 360.0,
                             mirrored=it.mirrored))
    if any(pools):
        return None
    return NestResult(pls, [], length_strip + fabric.margin_start + fabric.margin_end, 0, elapsed, seed, stopped, [])


def parse_svg(path, groups, fabric, seed=0, elapsed=0.0, stopped=False) -> NestResult | None:
    m = re.match(r"\d+_([\d.]+)_", os.path.basename(path))
    try:
        txt = open(path, encoding="utf-8").read()
    except OSError:
        return None
    entries = [(int(a), float(b), float(c), float(d)) for a, b, c, d in _USE.findall(txt)]
    return _to_result(entries, groups, fabric, float(m.group(1)) if m else 0.0, seed, elapsed, stopped)


def parse_json(path, groups, fabric, seed=0, elapsed=0.0) -> NestResult | None:
    try:
        sol = json.load(open(path, encoding="utf-8"))["solution"]
    except (OSError, ValueError, KeyError):
        return None
    entries = [(p["item_id"], p["transformation"]["translation"][0], p["transformation"]["translation"][1],
                p["transformation"]["rotation"]) for p in sol["layout"]["placed_items"]]
    return _to_result(entries, groups, fabric, float(sol["strip_width"]), seed, elapsed, False)


def run(items: list[NestItem], fabric, settings, time_limit: float, progress=None, stop_event=None,
        warm: NestResult | None = None, workers: int | None = None) -> NestResult | None:
    """Run sparrow; returns its best feasible layout (or None if the engine is missing / failed)."""
    exe = find_binary()
    if exe is None or not items:
        return None
    work = tempfile.mkdtemp(prefix="level7_sparrow_")
    t0 = time.monotonic()
    try:
        inst, groups = build_instance(items, fabric)
        src = warm_solution(inst, groups, warm, fabric) if warm is not None else None
        path = os.path.join(work, "job.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(src or inst, fh)
        workers = workers or max(1, (os.cpu_count() or 2) - 1)
        cmd = [exe, "-i", path, "-t", str(max(1, int(round(time_limit)))), "-s", str(int(settings.seed)),
               "--workers", str(workers)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(cmd, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=flags)
        sols = os.path.join(work, "output", "sols_level7")
        best, best_len, seen = None, None, set()
        stopped = False
        while proc.poll() is None:
            if stop_event is not None and stop_event.is_set():
                stopped = True
                proc.kill()
                break
            if time.monotonic() - t0 > time_limit + 60:
                proc.kill()
                break
            time.sleep(0.4)
            try:
                names = os.listdir(sols)
            except OSError:
                continue
            for n in sorted(names, key=lambda s: int(s.split("_", 1)[0]) if s.split("_", 1)[0].isdigit() else -1):
                if n in seen or not n.endswith(".svg") or not any(n.endswith(f"_{t}.svg") for t in FEASIBLE):
                    continue
                seen.add(n)
                m = re.match(r"\d+_([\d.]+)_", n)
                if m is None or (best_len is not None and float(m.group(1)) >= best_len):
                    continue
                r = parse_svg(os.path.join(sols, n), groups, fabric, settings.seed, time.monotonic() - t0)
                if r is not None:
                    best, best_len = r, float(m.group(1))
                    if progress:
                        progress({"elapsed": time.monotonic() - t0, "evaluations": len(seen),
                                  "length": r.length, "unplaced": 0, "result": r, "final": False})
        proc.wait(timeout=30)
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
        shutil.rmtree(work, ignore_errors=True)
