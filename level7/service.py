"""Application services shared by the GUI and the command line."""
from __future__ import annotations

import os
import threading
import time
from collections import Counter

from .model import CutOrder, FabricSettings, Marker, NestSettings, Placement, Project
from .nesting.engine import HALT_REASON, build_items, grain_rotations
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
    first = not tags                               # first addition: the session's own model gets a tag too
    if first:
        tags = [_make_tag(proj.name, [])]
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
    if first:                                      # only now: a refused file leaves the session unchanged
        namespace_project(proj, tags[0])
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
    t0 = time.monotonic()
    # the start has a hard time limit: a big job's first layout can take minutes (it ran past the timer before)
    start = run_parallel(items, fabric, replace(settings, time_limit=t_start, hard_time=True), workers=workers,
                         progress=progress, stop_event=stop_event)
    if stop_event is not None and stop_event.is_set():
        start.stopped = True
        return start, "builtin"
    remaining = max(5.0, total - (time.monotonic() - t0))

    def fallback():
        """sparrow gave nothing usable: a start cut short by its time limit is not a result - complete it with
        the built-in engine in the time that is left (the first layout completes, Stop still answers)."""
        if not any(u.reason == HALT_REASON for u in start.unplaced) or \
                (stop_event is not None and stop_event.is_set()):
            start.stopped = bool(stop_event is not None and stop_event.is_set())
            return start, "builtin"
        left = max(5.0, total - (time.monotonic() - t0))
        res2 = run_parallel(items, fabric, replace(settings, time_limit=left, hard_time=False), workers=workers,
                            progress=progress, stop_event=stop_event)
        return res2, "builtin"

    def prog(d):
        if progress:
            progress({**d, "engine": "sparrow"})
    res = sparrow.run(items, fabric, settings, remaining, progress=prog, stop_event=stop_event,
                      warm=start if not start.unplaced else None, workers=workers)
    if res is None:
        return fallback()
    allowed = {(it.piece_uid, it.mirrored): it.rotations for it in items}
    check = validate_marker(proj, Marker(name="check", fabric=fabric, placements=res.placements, length=res.length),
                            allowed_rotations=allowed)
    # compare true lengths (cut contours): the built-in length is measured on its grown search shapes
    start_len = validate_marker(proj, Marker(name="start", fabric=fabric, placements=start.placements)).length
    res.length = check.length
    # 90° turns were explicitly allowed by the user: their grain warnings do not disqualify sparrow's layout
    bad = [i for i in check.issues if not (i.kind == "grain" and settings.allow_rotation_90)]
    if bad or (len(res.unplaced), res.length) >= (len(start.unplaced), start_len):
        return fallback() if bad or res.unplaced else (start, "builtin")
    res.evaluations += start.evaluations
    return res, "sparrow"


def default_cut_order(proj: Project) -> CutOrder:
    co = CutOrder(size_quantities={s: 0 for s in proj.size_names})
    for p in proj.pieces:
        co.piece_counts[p.uid] = (p.default_count, p.default_mirrored) if p.production else (0, 0)
    mats = Counter(p.material for p in proj.pieces if p.production and p.material)
    co.material = mats.most_common(1)[0][0] if mats else None
    return co


ADDED_TO_ORDER = "added to the order - not placed yet (nest again or drag it in)"


def marker_material(proj: Project, marker: Marker) -> str | None:
    """The material a marker was made of (all its pieces share one), else None."""
    pcs = {p.uid: p for p in proj.pieces}
    mats = {pcs[pl.piece_uid].material for pl in marker.placements if pl.piece_uid in pcs}
    return next(iter(mats)) if len(mats) == 1 else None


def sync_marker_to_order(proj: Project, marker: Marker, spare: list | None = None) -> tuple[int, int]:
    """The marker follows the cut order at once (like GRAFIS): copies no longer ordered (a size quantity lowered,
    a size or part switched off, fewer copies) leave the marker - unplaced ones first -, newly ordered copies are
    added as not placed. Rows excluded with the strip check box only affect the next nesting run. The material
    is the marker's own (the "material to nest" choice belongs to the next run). ``spare``: copies removed by
    earlier syncs; ordered again, they come back where they were (a quantity 1 -> 0 -> 1 keeps the layout);
    the copies removed now are added to it. Returns (removed, added)."""
    from .model import LayType
    co = proj.cut_order
    material = marker_material(proj, marker) if marker.placements else co.material
    excluded = {(sz, int(b)) for sz, b in (getattr(co, "excluded", None) or [])}
    need: Counter = Counter()
    for piece in proj.pieces:
        n, m = co.piece_counts.get(piece.uid, (0, 0))
        if n + m == 0 or (material and piece.material and piece.material != material):
            continue
        if marker.fabric.lay_type in (LayType.FACE_TO_FACE, LayType.FOLDED):
            n, m = max(n, m), 0
        for size, qty in co.size_quantities.items():
            if (qty or 0) <= 0 or size not in piece.sizes or (piece.model and not size.startswith(piece.model + ":")):
                continue
            for b in range(1, qty + 1):
                if (size, b) in excluded:
                    continue
                need[(piece.uid, size, b, False)] += n
                need[(piece.uid, size, b, True)] += m
    have: dict = {}
    for pl in marker.placements:
        have.setdefault((pl.piece_uid, pl.size, pl.bundle, pl.mirrored), []).append(pl)
    drop: set = set()
    pcs = {p.uid: p for p in proj.pieces}
    for key, pls in have.items():
        if key[0] not in pcs or key[1] not in pcs[key[0]].sizes or (key[1], key[2]) in excluded:
            continue                        # no geometry for that size (its notice stays) / row switched off
        extra = len(pls) - need.get(key, 0)
        if extra > 0:                       # unplaced copies go first, then the last placed ones
            order = ([pl for pl in pls if not pl.placed] + [pl for pl in reversed(pls) if pl.placed and not pl.pinned]
                     + [pl for pl in reversed(pls) if pl.placed and pl.pinned])        # pinned copies go last
            drop |= {id(pl) for pl in order[:extra]}
    uids = {pl.uid for pl in marker.placements}
    added, k = [], 0
    sx, sy = marker.fabric.scale
    spare = spare if spare is not None else []
    for key, cnt in need.items():
        for _ in range(cnt - len(have.get(key, []))):
            back = next((pl for pl in spare if (pl.piece_uid, pl.size, pl.bundle, pl.mirrored) == key
                         and pl.uid not in uids), None)
            if back is not None:                  # removed by an earlier change of the order: same place again
                spare.remove(back)
                uids.add(back.uid)
                added.append(back)
                continue
            k += 1
            while f"a{k}" in uids or any(pl.uid == f"a{k}" for pl in spare):
                k += 1
            uids.add(f"a{k}")
            added.append(Placement(f"a{k}", key[0], key[1], key[2], mirrored=key[3], placed=False, sx=sx, sy=sy,
                                   reason=ADDED_TO_ORDER))
    if drop or added:
        spare.extend(pl for pl in marker.placements if id(pl) in drop)
        marker.placements = [pl for pl in marker.placements if id(pl) not in drop] + added
    return len(drop), len(added)


def required_copies(items) -> dict:
    return dict(Counter((i.piece_uid, i.size, i.mirrored) for i in items))


def run_nesting(proj: Project, fabric: FabricSettings, settings: NestSettings, cut_order: CutOrder | None = None,
                pinned=None, progress=None, stop_event: threading.Event | None = None, workers: int | None = None,
                name: str | None = None, placements=None, keep_out=None) -> tuple[Marker, dict]:
    """Nest the cut order - or, with ``placements``, re-nest exactly those copies (pieces left in a marker);
    ``keep_out`` (copies the user took out of the marker) stay in the result as not placed.

    ``settings.best_of`` > 1 ("best result"): that many attempts one after the other with different seeds (each
    with the full time limit); the valid marker with the fewest unplaced pieces and the shortest length wins."""
    from dataclasses import replace
    n = max(1, int(getattr(settings, "best_of", 1) or 1))
    if n == 1:
        return _run_once(proj, fabric, settings, cut_order, pinned, progress, stop_event, workers, name,
                         placements, keep_out)
    best = None
    tried = []
    for k in range(n):
        if stop_event is not None and stop_event.is_set() and best is not None:
            break
        st = replace(settings, seed=settings.seed + 1000 * k, best_of=1)

        def prog(d, k=k):
            if progress:
                progress({**d, "attempt": k + 1, "attempts": n, "final": False})
        m, info = _run_once(proj, fabric, st, cut_order, pinned, prog, stop_event, workers, name, placements,
                            keep_out)
        unpl = sum(1 for p in m.placements if not p.placed)
        tried.append((st.seed, round(m.length, 1), info["validation"].ok))
        key = (not info["validation"].ok, unpl, m.length)
        if best is None or key < best[0]:
            best = (key, m, info)
    _, m, info = best
    info["attempts"] = tried
    if progress:
        progress({"elapsed": 0.0, "evaluations": info.get("evaluations", 0), "length": m.length, "unplaced": 0,
                  "result": None, "final": True})
    return m, info


def _run_once(proj, fabric, settings, cut_order, pinned, progress, stop_event, workers, name, placements,
              keep_out) -> tuple[Marker, dict]:
    from .nesting.parallel import run_parallel
    co = cut_order or proj.cut_order
    if placements is not None:
        from .nesting.engine import items_from_placements
        items, unplaced, warnings = items_from_placements(proj, placements, fabric, settings)
        pinned = [it.pinned for it in items if it.pinned is not None]
    else:
        items, unplaced, warnings = build_items(proj, co.size_quantities, co.piece_counts, fabric, settings, pinned,
                                               material=co.material, excluded=getattr(co, "excluded", None))
    if not items and not unplaced:
        raise ValueError("nothing to nest: set size quantities and piece counts")
    t0 = time.monotonic()
    engine_used = "builtin"
    if items and _use_sparrow(settings, fabric, pinned) and not any(it.match for it in items):
        # (plaid matching: sparrow cannot keep pieces on pattern lines - the built-in engine does)
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
    from dataclasses import replace as _replace
    for pl in keep_out or []:                    # taken out by the user: still to place (strip), not nested
        marker.placements.append(_replace(pl, placed=False, pinned=False, reason=pl.reason or "taken out of the marker"))
    for pl in marker.placements:                 # unplaced copies too: placed later by hand with the same shrinkage
        pl.sx, pl.sy = fabric.scale
    allowed = {}
    for it in items:
        allowed[(it.piece_uid, it.mirrored)] = it.rotations
    for pl in marker.placements:
        if pl.pinned:
            allowed.setdefault((pl.piece_uid, pl.mirrored), []).append(pl.rotation)
    req = required_copies(items)
    for pl in keep_out or []:
        key = (pl.piece_uid, pl.size, pl.mirrored)
        req[key] = req.get(key, 0) + 1
    for u in unplaced:                           # copies refused before nesting (unknown grain, missing size)
        key = (u.piece_uid, u.size, u.mirrored)
        req[key] = req.get(key, 0) + 1
    v = validate_marker(proj, marker, required={k: n for k, n in req.items()}, allowed_rotations=allowed)
    st = marker_stats(proj, marker)
    marker.length = st["length_mm"]
    marker.stats = st
    info = {"validation": v, "warnings": warnings, "evaluations": res.evaluations, "elapsed": res.elapsed,
            "stopped": res.stopped, "history": res.history, "max_search_deviation": None, "engine": engine_used,
            # pieces left out because Stop / the time limit came before the first layout was complete
            "cut_short": sum(1 for u in res.unplaced if u.reason == HALT_REASON)}
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
    if fmt == "scb":
        from .formats.grafis.writer import write_scb
        template = config or scb_template(proj)
        if not template:
            raise ValueError("saving as GRAFIS SCB needs a GRAFIS SCB of this model as template")
        return write_scb(template, proj, marker, path)
    raise ValueError(fmt)


def mdl_template(proj: Project) -> str | None:
    """The GRAFIS MDL this session was read from (template for writing MDL), single-model sessions only."""
    if any(p.model for p in proj.pieces) or not proj.sources or proj.sources[0].kind != "mdl":
        return None          # e.g. an SCB session completed from its MDL: its order is the marker's, not the model's
    src = proj.sources[0]
    return src.path if os.path.isfile(src.path) else None


def scb_template(proj: Project) -> str | None:
    """The GRAFIS SCB this session was read from (template for writing SCB), if any and still on disk; for a
    session read from an MDL: an SCB of the same model next to it (see find_scb_for_model)."""
    for src in proj.sources:
        if src.kind == "scb" and os.path.isfile(src.path):
            return src.path
    mdl = mdl_template(proj)
    return find_scb_for_model(proj, os.path.dirname(mdl)) if mdl else None


def find_scb_for_model(proj: Project, folder: str, limit: int = 200) -> str | None:
    """A GRAFIS SCB in ``folder`` (or one level below) whose part list holds every part ``proj`` nests (matched as
    write_scb does, see formats.grafis.writer.part_map) - a GRAFIS marker of this model; the newest is returned."""
    from .formats.grafis.container import read_container
    from .formats.grafis.textsections import parse_text
    from .formats.grafis.writer import check_geometry, part_map, template_pieces
    co = proj.cut_order
    uids = {p.uid for p in proj.pieces if any(co.piece_counts.get(p.uid, (0, 0)))}
    want = {(p.number, p.name.strip()) for p in proj.pieces if p.uid in uids}
    if not want or not os.path.isdir(folder):
        return None
    found = []
    for root in [folder] + [os.path.join(folder, d) for d in _listdir(folder) if os.path.isdir(os.path.join(folder, d))]:
        for n in _listdir(root):
            if n.lower().endswith(".scb"):
                f = os.path.join(root, n)
                try:
                    found.append((os.path.getmtime(f), f))
                except OSError:          # vanished / dangling link / offline network file
                    continue
    found.sort(reverse=True)
    # cache keyed by the folder's SCBs (names + times): a newer SCB saved by GRAFIS is seen at once
    key = (os.path.abspath(folder), frozenset(want), tuple(found[:limit]))
    if key in _SCB_FOUND:
        return _SCB_FOUND[key]
    found = [f for _t, f in found]
    for f in found[:limit]:
        try:
            tb = read_container(f).get(2, 1, 0, 0)
            ts = parse_text(tb.payload) if tb is not None else None
        except Exception:
            continue
        if ts is None:
            continue
        try:   # names, then the shapes (an SCB of another model / an older state of this one is skipped)
            tp = template_pieces(f)
            pmap = part_map(proj, ts.tlist, uids, tp)
            used = {(u, sz) for u in uids for sz, q in co.size_quantities.items()
                    if q and sz in proj.piece(u).sizes}
            check_geometry(f, proj, pmap, used, tp)
        except Exception:
            continue
        _SCB_FOUND[key] = f
        return f
    _SCB_FOUND[key] = None
    return None


_SCB_FOUND: dict = {}


def _listdir(folder: str) -> list[str]:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []
