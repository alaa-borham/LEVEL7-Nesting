"""Generic DXF export (ezdxf). Units: millimetres ($INSUNITS = 4).

Layers are separated per role. Source geometry from GRAFIS is already stored as
polylines (evaluated curves), so polylines are written vertex-for-vertex: no extra
approximation is introduced by this exporter. The output is a generic DXF; it is NOT
labelled AAMA/ASTM (those rule sets are not implemented).
"""
from __future__ import annotations

import ezdxf

from .scene import LAYERS, Scene

LAYER_COLORS = {"CUT": 7, "SEAM": 3, "INTERNAL": 8, "NOTCH": 1, "MARK": 6, "GRAIN": 5, "TEXT": 2, "PIECE_NAME": 2, "BORDER": 4}


def write_dxf(scene: Scene, path: str, dxfversion: str = "R2000") -> dict:
    doc = ezdxf.new(dxfversion=dxfversion, setup=False)
    doc.units = 4  # mm
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name in LAYERS:
        if name not in doc.layers:
            doc.layers.add(name, color=LAYER_COLORS.get(name, 7))
    msp = doc.modelspace()
    n = 0
    for p in scene.paths:
        if len(p.points) < 2:
            continue
        msp.add_lwpolyline(p.points, close=p.closed, dxfattribs={"layer": p.layer})
        n += 1
    for t in scene.texts:
        msp.add_text(t.text, height=t.height, rotation=t.rotation,
                     dxfattribs={"layer": t.layer, "insert": t.position})
    for pt in scene.points:
        msp.add_point(pt.position, dxfattribs={"layer": pt.layer})
    doc.saveas(path, encoding="utf-8")
    return {"polylines": n, "texts": len(scene.texts), "points": len(scene.points)}


def read_dxf_paths(path: str) -> dict[str, list[tuple[list[tuple[float, float]], bool]]]:
    doc = ezdxf.readfile(path)
    out: dict[str, list] = {}
    for e in doc.modelspace().query("LWPOLYLINE"):
        out.setdefault(e.dxf.layer, []).append(([(p[0], p[1]) for p in e.get_points("xy")], bool(e.closed)))
    return out
