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
        issues = list(res.issues)
        if ext == ".scb" and missing_geometry(proj):
            mdl = find_model_file(path, proj)
            if mdl:
                n = supplement_from_model(proj, mdl)
                issues.append(f"{n} piece sizes missing in the SCB were loaded from the model file {mdl}")
        return proj, issues
    if ext == ".dxf":
        if _is_aama(path):
            from .readers.aama import read_aama
            return read_aama(path)
        from .readers.dxf import read_dxf
        return read_dxf(path)
    if ext == ".l7n":
        from .project_storage.store import load_project
        return load_project(path), []
    raise ValueError(f"unsupported file type: {ext}")


def missing_geometry(proj: Project, sizes=None) -> dict[str, list[str]]:
    """{size: [piece names]} for production pieces that have no geometry in a size (requested or known)."""
    sizes = list(sizes) if sizes is not None else list(proj.size_names)
    out: dict[str, list[str]] = {}
    for p in proj.pieces:
        if not p.production:
            continue
        for s in sizes:
            if s not in p.sizes:
                out.setdefault(s, []).append(p.name)
    return out


def find_model_file(scb_path: str, proj: Project) -> str | None:
    """The GRAFIS model (MDL) belonging to an SCB: the MODEL name stored in the SCB, else an MDL in the same
    folder that contains the same part IDs."""
    folder = os.path.dirname(os.path.abspath(scb_path))
    model = (proj.sbinfo or {}).get("MODEL", "")
    if model:
        cand = os.path.join(folder, os.path.basename(model.replace("\\", "/")))
        if os.path.isfile(cand):
            return cand
    ids = {p.source_id for p in proj.pieces if p.source_id}
    try:
        names = sorted(f for f in os.listdir(folder) if f.lower().endswith(".mdl"))
    except OSError:
        return None
    from .formats.grafis.container import read_container
    from .formats.grafis.textsections import parse_text
    for f in names:
        full = os.path.join(folder, f)
        try:
            cont = read_container(full)
            tb = cont.by_id().get((2, 1, 0, 0))
            if tb is not None and ids & {t.piece_id for t in parse_text(tb.payload).tlist}:
                return full
        except Exception:
            continue
    return None


def supplement_from_model(proj: Project, mdl_path: str) -> int:
    """Copy sizes that are missing in the project's pieces from the model file (matched by GRAFIS part ID,
    else part number). Returns the number of piece sizes added."""
    from .readers.grafis import read_grafis
    model = read_grafis(mdl_path).project
    by_id = {p.source_id: p for p in model.pieces if p.source_id}
    by_num = {p.number: p for p in model.pieces if p.number is not None}
    added = 0
    for p in proj.pieces:
        src = by_id.get(p.source_id) or by_num.get(p.number)
        if src is None:
            continue
        for s, g in src.sizes.items():
            if s not in p.sizes:
                p.sizes[s] = g
                added += 1
        if p.grain_angle is None:
            p.grain_angle = src.grain_angle
    for s in model.size_names:
        if s not in proj.size_names:
            proj.size_names.append(s)
    proj.sources.extend(src for src in model.sources if src.path not in {x.path for x in proj.sources})
    return added


MAX_MODELS = 15
MODEL_SEP = ":"


def model_tags(proj: Project) -> list[str]:
    seen = []
    for p in proj.pieces:
        if p.model and p.model not in seen:
            seen.append(p.model)
    return seen


def size_label(tags: list[str], size: str) -> str:
    """Short display of a session size: "2·M" for size M of the 2nd model (full "tag:size" in tables)."""
    if tags and MODEL_SEP in size:
        tag, s = size.split(MODEL_SEP, 1)
        if tag in tags:
            return f"{tags.index(tag) + 1}·{s}"
    return size


def _make_tag(name: str, taken) -> str:
    import re
    base = re.sub(r"\s+", " ", re.sub(r"[:|]", " ", name)).strip()[:18] or "model"
    tag, k = base, 2
    while tag in taken:
        tag, k = f"{base} {k}", k + 1
    return tag


def namespace_project(proj: Project, tag: str) -> None:
    """Prefix every size of this model with its tag ("pants:44") so several models can share one session
    even when their size names are equal. Base entries become "base:<tag>:<name>"."""
    def ren(k: str) -> str:
        return f"base:{tag}{MODEL_SEP}{k[5:]}" if k.startswith("base:") else f"{tag}{MODEL_SEP}{k}"
    for p in proj.pieces:
        if p.model:
            continue
        p.model = tag
        p.sizes = {ren(k): g for k, g in p.sizes.items()}
        for g in p.sizes.values():
            g.size = ren(g.size) if g.size and not g.size.startswith(tag + MODEL_SEP) else g.size
    proj.size_names = [s if s.startswith(tag + MODEL_SEP) else ren(s) for s in proj.size_names]
    co = proj.cut_order
    co.size_quantities = {(k if k.startswith(tag + MODEL_SEP) else ren(k)): v for k, v in co.size_quantities.items()}
    for m in proj.markers:
        for pl in m.placements:
            if not pl.size.startswith(tag + MODEL_SEP):
                pl.size = ren(pl.size)
        if m.stats and isinstance(m.stats.get("by_size"), dict):
            m.stats["by_size"] = {ren(k): v for k, v in m.stats["by_size"].items()}


def add_model(proj: Project, path: str) -> tuple[Project, list[str]]:
    """Add another model file (MDL / SCB / DXF / AAMA / project) to a session: its pieces, sizes (prefixed with
    the model tag), cut order and markers. Pieces of all models can then be nested into one marker."""
    tags = model_tags(proj)
    if not tags:                                   # first addition: tag the models already in the session
        tags = [_make_tag(proj.name, [])]
        namespace_project(proj, tags[0])
    other, issues = open_any(path)
    have = {src.sha256 for src in proj.sources if src.sha256}
    if any(src.sha256 in have for src in other.sources if src.sha256):
        raise ValueError(f"model already in this session: {os.path.basename(path)}")
    if any(p.model for p in other.pieces):         # a saved multi-model project: keep its tags, avoid clashes
        new_tags = model_tags(other)
    else:
        new_tags = [_make_tag(other.name, tags)]
        namespace_project(other, new_tags[0])
    clash = set(new_tags) & set(tags)
    if clash:
        raise ValueError(f"model already in this session: {', '.join(sorted(clash))}")
    if len(tags) + len(new_tags) > MAX_MODELS:
        raise ValueError(f"at most {MAX_MODELS} model files per session")
    proj.pieces.extend(other.pieces)
    proj.size_names.extend(s for s in other.size_names if s not in proj.size_names)
    proj.sources.extend(other.sources)
    proj.markers.extend(other.markers)
    proj.cut_order.size_quantities.update(other.cut_order.size_quantities)
    proj.cut_order.piece_counts.update(other.cut_order.piece_counts)
    if not proj.cut_order.material:
        proj.cut_order.material = other.cut_order.material
    if proj.name and other.name and other.name not in proj.name:
        proj.name = f"{proj.name} + {other.name}" if " + " not in proj.name else proj.name
    return other, issues


def _is_aama(path: str) -> bool:
    """AAMA/ASTM DXF: a sibling .rul file or 'Piece Name:' annotations in blocks."""
    if os.path.exists(os.path.splitext(path)[0] + ".rul") or os.path.exists(os.path.splitext(path)[0] + ".RUL"):
        return True
    try:
        with open(path, "rb") as fh:
            return b"Piece Name:" in fh.read(4_000_000)
    except OSError:
        return False


def _use_sparrow(settings, fabric, pinned) -> bool:
    from .nesting import sparrow
    engine = os.environ.get("LEVEL7_ENGINE", settings.engine or "auto")
    return engine in ("auto", "sparrow") and sparrow.available() and not pinned and not fabric.max_length


def _nest_with_sparrow(proj, items, fabric, settings, workers, progress, stop_event):
    """LEVEL7's engine builds a valid start quickly, sparrow compresses it for the rest of the time; the shorter
    layout that passes LEVEL7's validator wins (so the result is never worse than the built-in start)."""
    from dataclasses import replace
    from .model import Marker
    from .nesting import sparrow
    from .nesting.parallel import run_parallel
    total = settings.time_limit or 30.0
    t_start = min(15.0, max(3.0, 0.15 * total))
    start = run_parallel(items, fabric, replace(settings, time_limit=t_start), workers=workers, progress=progress,
                         stop_event=stop_event)
    if stop_event is not None and stop_event.is_set():
        return start, "builtin"
    remaining = max(5.0, total - t_start)

    def prog(d):
        if progress:
            progress({**d, "engine": "sparrow"})
    res = sparrow.run(items, fabric, settings, remaining, progress=prog, stop_event=stop_event,
                      warm=start if not start.unplaced else None, workers=workers)
    if res is None:
        return start, "builtin"
    check = validate_marker(proj, Marker(name="check", fabric=fabric, placements=res.placements, length=res.length),
                            allowed_rotations={(it.piece_uid, it.mirrored): it.rotations for it in items})
    if not check.ok or (len(res.unplaced), res.length) >= (len(start.unplaced), start.length):
        return start, "builtin"
    res.evaluations += start.evaluations
    return res, "sparrow"


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
    engine_used = "builtin"
    if items and _use_sparrow(settings, fabric, pinned):
        res, engine_used = _nest_with_sparrow(proj, items, fabric, settings, workers, progress, stop_event)
    elif items:
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
            "stopped": res.stopped, "history": res.history, "max_search_deviation": None, "engine": engine_used}
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
