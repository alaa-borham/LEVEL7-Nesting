"""Application services shared by the GUI and the command line."""
from __future__ import annotations

import os
import threading
import time
from collections import Counter

from .model import CutOrder, FabricSettings, Marker, NestSettings, Project
from .nesting.engine import build_items, grain_rotations
from .validation.checker import marker_stats, validate_marker


def open_any(path: str) -> tuple[Project, list[str]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mdl", ".scb"):
        from .readers.grafis import read_grafis
        res = read_grafis(path)
        proj = res.project
        if ext == ".mdl" or not proj.cut_order.piece_counts:
            proj.cut_order = default_cut_order(proj)
        return proj, res.issues
    if ext == ".dxf":
        from .readers.dxf import read_dxf
        return read_dxf(path)
    if ext == ".l7n":
        from .project_storage.store import load_project
        return load_project(path), []
    raise ValueError(f"unsupported file type: {ext}")


def default_cut_order(proj: Project) -> CutOrder:
    co = CutOrder(size_quantities={s: 0 for s in proj.size_names})
    for p in proj.pieces:
        co.piece_counts[p.uid] = (p.default_count, p.default_mirrored) if p.production else (0, 0)
    mats = Counter(p.material for p in proj.pieces if p.production and p.material)
    co.material = mats.most_common(1)[0][0] if mats else None
    return co


def required_copies(items) -> dict:
    return dict(Counter((i.piece_uid, i.size, i.mirrored) for i in items))


def run_nesting(proj: Project, fabric: FabricSettings, settings: NestSettings, cut_order: CutOrder | None = None,
                pinned=None, progress=None, stop_event: threading.Event | None = None, workers: int | None = None,
                name: str | None = None) -> tuple[Marker, dict]:
    from .nesting.parallel import run_parallel
    co = cut_order or proj.cut_order
    items, unplaced, warnings = build_items(proj, co.size_quantities, co.piece_counts, fabric, settings, pinned,
                                           co.material)
    if not items and not unplaced:
        raise ValueError("nothing to nest: set size quantities and piece counts")
    t0 = time.monotonic()
    if items:
        res = run_parallel(items, fabric, settings, workers=workers, progress=progress, stop_event=stop_event)
    else:   # every requested copy was rejected (e.g. unknown grain): report them, do not fail
        from .nesting.engine import NestResult
        res = NestResult([], [], fabric.margin_start + fabric.margin_end)
    marker = Marker(name=name or f"{proj.name} {fabric.width:g}mm", fabric=fabric, placements=res.placements,
                    origin="nested", seed=settings.seed, compute_time=time.monotonic() - t0)
    from .model import Placement
    for u in list(res.unplaced) + list(unplaced):
        marker.placements.append(Placement(uid=u.item_uid or f"u{len(marker.placements)}", piece_uid=u.piece_uid,
                                           size=u.size, mirrored=u.mirrored, placed=False, reason=u.reason))
    allowed = {}
    for it in items:
        allowed[(it.piece_uid, it.mirrored)] = it.rotations
    for pl in marker.placements:
        if pl.pinned:
            allowed.setdefault((pl.piece_uid, pl.mirrored), []).append(pl.rotation)
    req = required_copies(items)
    v = validate_marker(proj, marker, required={k: n for k, n in req.items()}, allowed_rotations=allowed)
    st = marker_stats(proj, marker)
    marker.length = st["length_mm"]
    marker.stats = st
    info = {"validation": v, "warnings": warnings, "evaluations": res.evaluations, "elapsed": res.elapsed,
            "stopped": res.stopped, "history": res.history, "max_search_deviation": None}
    return marker, info


def allowed_rotation_map(proj: Project, settings: NestSettings) -> dict:
    out = {}
    for p in proj.pieces:
        for mir in (False, True):
            r, _ = grain_rotations(p, mir, settings)
            out[(p.uid, mir)] = r
    return out


def export_marker(proj: Project, marker: Marker, fmt: str, path: str, config=None, diagnostic_iso: bool = False,
                  job_name: str | None = None):
    from .exporters.scene import marker_scene
    sc = marker_scene(proj, marker)
    if fmt == "plt":
        from .exporters.plt import write_plt
        return write_plt(sc, path, config)
    if fmt == "dxf":
        from .exporters.dxf import write_dxf
        return write_dxf(sc, path)
    if fmt == "iso":
        from .exporters.iso import write_iso
        name = job_name or os.path.splitext(os.path.basename(path))[0]
        return write_iso(sc, path, config, diagnostic=diagnostic_iso, job_name=name)
    raise ValueError(fmt)
