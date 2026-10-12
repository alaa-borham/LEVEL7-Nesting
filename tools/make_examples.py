"""Generate verified example outputs from the sample files.

    python tools/make_examples.py [--time 30]

Writes examples/: sample project (.l7n) with the original SCB marker and new markers
for 1400 / 1430 / 1500 mm, PLT/DXF exports, a diagnostic ISO preview, a 1000 mm
calibration square, and VERIFICATION.json (re-read + compare results).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def maxdev(a, b):
    if len(a) != len(b):
        return float("inf")
    return max(math.dist(p, q) for p, q in zip(a, b))


def verify_exports(proj, marker, base, out):
    from level7.exporters.dxf import read_dxf_paths, write_dxf
    from level7.exporters.iso import simulate_iso, write_iso
    from level7.exporters.plt import PlotterConfig, read_plt, write_plt
    from level7.exporters.scene import marker_scene
    sc = marker_scene(proj, marker)
    cut = [p.points + [p.points[0]] for p in sc.paths if p.layer == "CUT"]
    cfg = PlotterConfig()
    write_plt(sc, base + ".plt", cfg)
    paths, labels = read_plt(base + ".plt", cfg)
    plt_cut = [p.points for p in paths if p.pen == cfg.pens["CUT"]]
    write_dxf(sc, base + ".dxf")
    d = read_dxf_paths(base + ".dxf")
    dxf_cut = [pts + [pts[0]] for pts, _c in d["CUT"]]
    write_iso(sc, base + "_DIAGNOSTIC.iso", diagnostic=True)
    iso_cut = simulate_iso(base + "_DIAGNOSTIC.iso")
    key = {(round(c[0][0], 2), round(c[0][1], 2)): c for c in cut}
    out[os.path.basename(base)] = {
        "cut_paths": len(cut),
        "plt": {"cut_paths": len(plt_cut), "max_dev_mm": max(maxdev(a, b) for a, b in zip(cut, plt_cut)),
                "labels_as_LB": len(labels), "non_cut_pens_paths": len(paths) - len(plt_cut)},
        "dxf": {"cut_paths": len(dxf_cut), "max_dev_mm": max(maxdev(a, b) for a, b in zip(cut, dxf_cut)),
                "layers": sorted(d)},
        "iso_diagnostic": {"cut_paths": len(iso_cut),
                           "max_dev_mm": max(maxdev(key[(round(c[0][0], 2), round(c[0][1], 2))], c) for c in iso_cut)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=float, default=30)
    a = ap.parse_args()
    from level7.exporters.plt import read_plt, write_plt
    from level7.exporters.scene import Path, Scene
    from level7.model import FabricSettings, NestSettings
    from level7.project_storage.store import save_project
    from level7.service import open_any, run_nesting
    from level7.validation.checker import marker_stats, validate_marker
    ex = os.path.join(ROOT, "examples")
    os.makedirs(ex, exist_ok=True)
    proj, issues = open_any(os.path.join(ROOT, "samples", "Neay blue pants-44.scb"))
    ver = {"read_issues": issues, "markers": {}, "exports": {}}
    orig = proj.markers[0]
    v = validate_marker(proj, orig)
    ver["markers"]["original_scb"] = {"validation": v.summary(), **marker_stats(proj, orig)}
    verify_exports(proj, orig, os.path.join(ex, "original_1430"), ver["exports"])
    for w in (1400, 1430, 1500):
        m, info = run_nesting(proj, FabricSettings(width=w), NestSettings(time_limit=a.time, seed=1))
        proj.markers.append(m)
        ver["markers"][f"nested_{w}"] = {"validation": info["validation"].summary(), "evaluations": info["evaluations"],
                                         "seed": 1, "time_limit_s": a.time, **m.stats}
        verify_exports(proj, m, os.path.join(ex, f"nested_{w}"), ver["exports"])
        print(w, round(m.length, 1), info["validation"].summary(), flush=True)
    save_project(proj, os.path.join(ex, "Neay_blue_pants_44.l7n"))
    from level7.exporters.plt import algotex_grafis_config
    from level7.exporters.scene import marker_scene
    for m in proj.markers:
        tag = "original_1430" if m.origin == "original" else f"nested_{m.fabric.width:g}"
        write_plt(marker_scene(proj, m), os.path.join(ex, f"{tag}_algotex.plt"), algotex_grafis_config())
    sq = Scene(paths=[Path("CUT", [(0, 0), (1000, 0), (1000, 1000), (0, 1000)], True)])
    write_plt(sq, os.path.join(ex, "calibration_1000mm_square.plt"))
    pts = read_plt(os.path.join(ex, "calibration_1000mm_square.plt"))[0][0].points
    ver["calibration_square"] = {"side_lengths_mm": [round(math.dist(p, q), 6) for p, q in zip(pts, pts[1:])]}
    with open(os.path.join(ex, "VERIFICATION.json"), "w", encoding="utf-8") as fh:
        json.dump(ver, fh, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(ver["exports"], indent=1))


if __name__ == "__main__":
    main()
