"""LEVEL7 project files (*.l7n): ZIP container with versioned JSON.

    project.json   {"format": "level7-nesting-project", "format_version": 1, ...}

The extracted geometry is stored completely, so a project opens without the source
MDL/SCB files (their path + SHA-256 are kept for traceability). Source files are
never modified.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import asdict

from ..model import (CutOrder, Drill, FabricSettings, Label, LayType, Marker, NestSettings, Notch, Piece,
                     PieceGeometry, Placement, Polyline, Project, SourceInfo)

FORMAT = "level7-nesting-project"
FORMAT_VERSION = 1


class ProjectFormatError(Exception):
    pass


def save_project(project: Project, path: str) -> None:
    d = asdict(project)
    for m in d["markers"]:
        m["fabric"]["lay_type"] = LayType(m["fabric"]["lay_type"]).value
    doc = {"format": FORMAT, "format_version": FORMAT_VERSION, "project": d}
    data = json.dumps(doc, ensure_ascii=False, indent=1)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", data)


def load_project(path: str) -> Project:
    try:
        with zipfile.ZipFile(path) as z:
            doc = json.loads(z.read("project.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise ProjectFormatError(f"not a LEVEL7 project: {e}") from e
    if doc.get("format") != FORMAT:
        raise ProjectFormatError("unknown project format")
    if doc.get("format_version", 0) > FORMAT_VERSION:
        raise ProjectFormatError(f"project format {doc['format_version']} is newer than supported {FORMAT_VERSION}")
    return project_from_dict(doc["project"])


def _pts(v):
    return [tuple(p) for p in v]


def _poly(d):
    return Polyline(_pts(d["points"]), d.get("closed", False), d.get("source_id"))


def _geom(d) -> PieceGeometry:
    return PieceGeometry(
        size=d["size"], cut=_pts(d["cut"]), corners=_pts(d.get("corners", [])), holes=[_pts(h) for h in d.get("holes", [])],
        seam=[_poly(s) for s in d.get("seam", [])], internal=[_poly(s) for s in d.get("internal", [])],
        notches=[Notch(tuple(n["position"]), tuple(n["direction"]) if n.get("direction") else None,
                       n.get("length", 5.0), n.get("source_id")) for n in d.get("notches", [])],
        drills=[Drill(tuple(x["position"]), x.get("code"), x.get("source_id")) for x in d.get("drills", [])],
        grain=_poly(d["grain"]) if d.get("grain") else None,
        labels=[Label(x["text"], tuple(x["position"]), x.get("height", 10.0),
                      tuple(x["box"]) if x.get("box") else None, x.get("angle", 0.0))
                for x in d.get("labels", [])],
        source_unit=d.get("source_unit", "mm"), unit_factor=d.get("unit_factor", 1.0),
        completeness=d.get("completeness", {}), source=d.get("source", ""))


def project_from_dict(d: dict) -> Project:
    pieces = []
    for p in d.get("pieces", []):
        pc = Piece(uid=p["uid"], source_id=p["source_id"], number=p.get("number"), name=p["name"],
                   material=p.get("material"), production=p.get("production", True),
                   default_count=p.get("default_count", 1), default_mirrored=p.get("default_mirrored", 0),
                   sizes={k: _geom(v) for k, v in p.get("sizes", {}).items()},
                   allowed_rotations=p.get("allowed_rotations", [0.0, 180.0]),
                   allow_mirror=p.get("allow_mirror", False), grain_angle=p.get("grain_angle"),
                   notes=p.get("notes", []))
        pieces.append(pc)
    markers = []
    for m in d.get("markers", []):
        f = dict(m["fabric"])
        f["lay_type"] = LayType(f.get("lay_type", "open"))
        mk = Marker(name=m["name"], fabric=FabricSettings(**f),
                    placements=[Placement(**pl) for pl in m.get("placements", [])],
                    length=m.get("length", 0.0), origin=m.get("origin", "nested"), seed=m.get("seed"),
                    compute_time=m.get("compute_time"), stats=m.get("stats", {}))
        markers.append(mk)
    co = d.get("cut_order", {})
    cut_order = CutOrder(size_quantities=co.get("size_quantities", {}),
                         piece_counts={k: tuple(v) for k, v in co.get("piece_counts", {}).items()},
                         material=co.get("material"))
    return Project(name=d.get("name", "untitled"), pieces=pieces, size_names=d.get("size_names", []),
                   sources=[SourceInfo(**s) for s in d.get("sources", [])], cut_order=cut_order,
                   nest_settings=NestSettings(**d.get("nest_settings", {})), markers=markers,
                   export_configs=d.get("export_configs", {}), reports=d.get("reports", {}),
                   sbinfo=d.get("sbinfo", {}))
