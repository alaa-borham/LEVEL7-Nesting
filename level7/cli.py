"""Command line interface.

    level7 info  FILE [--json]
    level7 nest  FILE --width 1430 [--sizes 44=2] [--time 30] [--seed 1] [--spacing 0] [-o out.l7n]
    level7 export PROJECT.l7n --marker -1 --format plt|dxf|iso|scb [--diagnostic] [--template SCB] -o FILE
    level7 compare FILE.scb --width 1500 [--time 30]
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _parse_sizes(spec: list[str] | None) -> dict[str, int]:
    out = {}
    for s in spec or []:
        k, _, v = s.partition("=")
        out[k] = int(v or 1)
    return out


def cmd_info(a):
    from .service import open_any
    proj, issues = open_any(a.file)
    if getattr(a, "json", False):                  # machine-readable (used by LEVEL7 MTM)
        from . import __version__
        print(json.dumps({"format": "level7-info", "format_version": 1, "level7_version": __version__,
                          "name": proj.name, "size_names": proj.size_names,
                          "pieces": [{"number": p.number, "name": p.name, "production": p.production,
                                      "material": p.material, "count": p.default_count,
                                      "mirrored": p.default_mirrored, "sizes": list(p.sizes)}
                                     for p in proj.pieces],
                          "issues": issues}, ensure_ascii=False))
        return 0
    print(f"{proj.name}: {len(proj.pieces)} pieces, sizes {proj.size_names}")
    for p in proj.pieces:
        print(f"  {p.number!s:>3} {p.name:<28} prod={p.production!s:<5} mat={p.material or '-'} "
              f"n={p.default_count} mirr={p.default_mirrored} sizes={len(p.sizes)} grain={p.grain_angle}")
    for m in proj.markers:
        print(f"marker {m.name}: width {m.fabric.width} length {m.length:.2f} placements {len(m.placements)}")
    if issues:
        print("issues:", *issues, sep="\n  ")
    return 0


def _nest(a, proj):
    from .model import FabricSettings, NestSettings
    from .service import run_nesting
    sizes = _parse_sizes(a.sizes)
    if sizes:
        proj.cut_order.size_quantities = sizes
    fab = FabricSettings(width=a.width, spacing=a.spacing, margin_left=a.margin, margin_right=a.margin,
                         buffer_x=a.buffer_x, buffer_y=a.buffer_y, shrink_x=a.shrink_x, shrink_y=a.shrink_y)
    st = NestSettings(time_limit=a.time, seed=a.seed, mode=a.mode, engine=getattr(a, "engine", "auto"))

    def prog(d):
        if d.get("final"):
            return
        if d.get("placing"):                     # first layout of a big job, piece by piece
            print(f"  {d.get('elapsed', 0.0):6.1f}s  first layout {d['placing']}/{d['of']} pieces", flush=True)
        elif d.get("length") is not None:
            print(f"  {d.get('elapsed', 0.0):6.1f}s  evaluations {d.get('evaluations', 0):6d}  "
                  f"length {d['length']:.1f} mm", flush=True)
    return run_nesting(proj, fab, st, progress=prog, workers=a.workers)


def cmd_nest(a):
    from .project_storage.store import save_project
    from .service import open_any
    proj, issues = open_any(a.file)
    marker, info = _nest(a, proj)
    proj.markers.append(marker)
    print(json.dumps({k: v for k, v in marker.stats.items() if k != "by_size"}, indent=1, default=str))
    print(info["validation"].summary())
    print("engine:", info.get("engine", "builtin"))
    for w in info["warnings"]:
        print("warning:", w)
    for pl in marker.placements:
        if not pl.placed:
            print("UNPLACED:", proj.piece(pl.piece_uid).name, pl.size, pl.reason)
    if a.output:
        save_project(proj, a.output)
        print("saved", a.output)
    return 0 if info["validation"].ok and all(pl.placed for pl in marker.placements) else 2


def cmd_compare(a):
    from .service import open_any
    from .validation.checker import marker_stats
    proj, _ = open_any(a.file)
    if not proj.markers:
        print("file has no marker")
        return 1
    orig = proj.markers[0]
    so = marker_stats(proj, orig)
    marker, info = _nest(a, proj)
    sn = marker.stats
    rows = [("width mm", so["width_mm"], sn["width_mm"]), ("length mm", so["length_mm"], sn["length_mm"]),
            ("efficiency %", so["efficiency_total_width_pct"], sn["efficiency_total_width_pct"]),
            ("consumption m", so["consumption_m"], sn["consumption_m"]), ("placed", so["placed"], sn["placed"])]
    print(f"{'':16}{'original':>12}{'new':>12}")
    for n, x, y in rows:
        print(f"{n:16}{x:12.2f}{y:12.2f}")
    print(info["validation"].summary())
    return 0


def cmd_export(a):
    from .exporters.iso import MachineProfile
    from .exporters.plt import PlotterConfig
    from .project_storage.store import ProjectFormatError
    from .service import export_marker, open_any
    try:
        proj, _ = open_any(a.project)
    except (OSError, ProjectFormatError, ValueError) as e:
        print(f"cannot open {a.project}: {e}")
        return 1
    if not -len(proj.markers) <= a.marker < len(proj.markers):
        print(f"{a.project} has {len(proj.markers)} marker(s); --marker {a.marker} does not exist")
        return 1
    m = proj.markers[a.marker]
    cfg = None
    if a.format == "iso" and a.iso_preset:
        from .exporters.iso import ISO_PRESETS
        cfg = ISO_PRESETS[a.iso_preset]()
    if a.format == "plt" and a.plt_preset:
        from .exporters.plt import PRESETS
        cfg = PRESETS[a.plt_preset]()
    if a.config:
        cfg = (PlotterConfig if a.format == "plt" else MachineProfile).load(a.config)
    if a.format == "scb":
        cfg = a.template
    from .exporters.iso import NotConfigured
    try:
        st = export_marker(proj, m, a.format, a.output, cfg, diagnostic_iso=a.diagnostic)
    except NotConfigured as e:
        print(f"{e} (--iso-preset bullmer_grafis / iecho, --config machine.json, or --diagnostic)")
        return 1
    except (OSError, ValueError) as e:          # e.g. SCB template / MDL problems, unwritable output
        print(f"export failed: {e}")
        return 1
    print(st)
    return 0


def cmd_batch(a):
    from . import batch
    from .exporters.iso import ISO_PRESETS
    from .exporters.plt import PRESETS
    if a.template:
        batch.write_template(a.orders)
        print("example list written:", a.orders)
        return 0
    orders = batch.parse_orders(a.orders)
    out = a.outdir or os.path.join(os.path.dirname(os.path.abspath(a.orders)),
                                   "LEVEL7_" + os.path.splitext(os.path.basename(a.orders))[0])

    def show(k, o):
        if o.status != "running":
            print(f"{o.name}: {o.status} {o.message}", flush=True)
    summary = batch.run_batch(orders, out, PRESETS[a.plt_preset](), ISO_PRESETS[a.iso_preset](), a.time, on_order=show)
    print("summary:", summary)
    return 0 if all(o.status == "done" for o in orders) else 2


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:  # Windows consoles default to cp1252/cp1256: never crash on Arabic names
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="level7")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info")
    s.add_argument("--json", action="store_true", help="machine-readable output (format level7-info v1)")
    s.add_argument("file")
    s.set_defaults(fn=cmd_info)
    for name, fn in (("nest", cmd_nest), ("compare", cmd_compare)):
        s = sub.add_parser(name)
        s.add_argument("file")
        s.add_argument("--width", type=float, required=True)
        s.add_argument("--sizes", nargs="*")
        s.add_argument("--time", type=float, default=30)
        s.add_argument("--seed", type=int, default=1)
        s.add_argument("--mode", default="balanced")
        s.add_argument("--engine", choices=["auto", "builtin"], default="auto",
                       help="auto: LEVEL7 start + sparrow compression when the engine is bundled")
        s.add_argument("--spacing", type=float, default=0.0)
        s.add_argument("--margin", type=float, default=0.0)
        s.add_argument("--buffer-x", type=float, default=0.0, help="extra buffer between pieces along the length (mm)")
        s.add_argument("--buffer-y", type=float, default=0.0, help="extra buffer between pieces across the width (mm)")
        s.add_argument("--shrink-x", type=float, default=0.0, help="shrinkage along the length (%%)")
        s.add_argument("--shrink-y", type=float, default=0.0, help="shrinkage across the width (%%)")
        s.add_argument("--workers", type=int, default=None)
        s.add_argument("-o", "--output")
        s.set_defaults(fn=fn)
    s = sub.add_parser("batch", help="nest, save and export a list of markers (Excel / CSV)")
    s.add_argument("orders")
    s.add_argument("-o", "--outdir", default=None)
    s.add_argument("--time", type=float, default=120, help="default seconds per marker")
    s.add_argument("--plt-preset", default="algotex_grafis")
    s.add_argument("--iso-preset", default="bullmer_grafis")
    s.add_argument("--template", action="store_true", help="write an example list to ORDERS and exit")
    s.set_defaults(fn=cmd_batch)
    s = sub.add_parser("export")
    s.add_argument("project")
    s.add_argument("--marker", type=int, default=-1)
    s.add_argument("--format", choices=("plt", "dxf", "iso", "scb"), required=True)
    s.add_argument("--template", help="scb: GRAFIS SCB of the same model (default: the project's own SCB)")
    s.add_argument("--config")
    s.add_argument("--diagnostic", action="store_true")
    s.add_argument("--plt-preset", choices=("generic", "algotex_grafis"))
    s.add_argument("--iso-preset", choices=("unconfigured", "bullmer_grafis", "iecho"))
    s.add_argument("-o", "--output", required=True)
    s.set_defaults(fn=cmd_export)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130
    except Exception as e:                 # one clear line instead of a traceback (LEVEL7_DEBUG=1 shows it)
        if os.environ.get("LEVEL7_DEBUG"):
            raise
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
