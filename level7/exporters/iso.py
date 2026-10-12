"""ISO (G-code style) cutting-file post-processor.

Target machine (user): Bullmer cutter (Germany). Its cut-file dialect is not publicly documented,
so no dialect is configured: the exact model and a reference cut file written by GRAFIS for it are
needed. Until a ``MachineProfile`` is marked
``verified``, only a DIAGNOSTIC PREVIEW can be produced; it is clearly marked as not
for production and uses generic codes. This module never talks to a machine.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .scene import Scene


@dataclass
class MachineProfile:
    name: str = "UNCONFIGURED"
    verified: bool = False               # True only after comparison with a real reference file
    units: str = "mm"                    # "mm" -> G21, "inch" -> G20
    decimals: int = 2
    swap_xy: bool = False
    flip_y: bool = False
    header: list[str] = field(default_factory=lambda: ["%", "G21", "G90"])
    footer: list[str] = field(default_factory=lambda: ["M30", "%"])
    rapid: str = "G0"
    feed: str = "G1"
    tool_down: str = "M14"               # placeholder codes - NOT a real dialect
    tool_up: str = "M15"
    notch_cmd: str = "M20"
    drill_cmd: str = "M21"
    layers_cut: list[str] = field(default_factory=lambda: ["CUT"])
    layers_notch: list[str] = field(default_factory=lambda: ["NOTCH"])
    layers_drill: list[str] = field(default_factory=list)  # symbol meaning unknown -> nothing drilled
    order: str = "nearest"               # nearest / as_is

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(**json.load(fh))


class NotConfigured(Exception):
    pass


def _fmt(v, d):
    return f"{v:.{d}f}"


def write_iso(scene: Scene, path: str, profile: MachineProfile | None = None, diagnostic: bool = False) -> dict:
    profile = profile or MachineProfile()
    if not profile.verified and not diagnostic:
        raise NotConfigured("ISO export is not configured for a verified machine profile; "
                            "only a diagnostic preview can be produced")
    d = profile.decimals
    lines = []
    if diagnostic or not profile.verified:
        lines += ["(DIAGNOSTIC PREVIEW - NOT FOR PRODUCTION)",
                  f"(profile: {profile.name}; machine dialect not verified)"]
    lines += profile.header
    jobs = [p for p in scene.paths if p.layer in profile.layers_cut + profile.layers_notch and len(p.points) >= 2]
    if profile.order == "nearest":
        jobs = _nearest_order(jobs)
    stats = {"cut_paths": 0, "notches": 0}
    for p in jobs:
        pts = list(p.points)
        if p.closed and pts[0] != pts[-1]:
            pts.append(pts[0])
        pts = [(y, x) if profile.swap_xy else (x, y) for x, y in pts]
        if profile.flip_y:
            pts = [(x, -y) for x, y in pts]
        if p.layer in profile.layers_notch:
            x, y = pts[0]
            lines.append(f"{profile.rapid} X{_fmt(x, d)} Y{_fmt(y, d)}")
            lines.append(profile.notch_cmd)
            stats["notches"] += 1
            continue
        x, y = pts[0]
        lines.append(f"{profile.rapid} X{_fmt(x, d)} Y{_fmt(y, d)}")
        lines.append(profile.tool_down)
        for x, y in pts[1:]:
            lines.append(f"{profile.feed} X{_fmt(x, d)} Y{_fmt(y, d)}")
        lines.append(profile.tool_up)
        stats["cut_paths"] += 1
    lines += profile.footer
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    stats["diagnostic"] = diagnostic or not profile.verified
    return stats


def _nearest_order(paths):
    rest = list(paths)
    out = []
    pos = (0.0, 0.0)
    while rest:
        k = min(range(len(rest)), key=lambda i: (rest[i].points[0][0] - pos[0]) ** 2 + (rest[i].points[0][1] - pos[1]) ** 2)
        p = rest.pop(k)
        out.append(p)
        pos = p.points[-1] if not p.closed else p.points[0]
    return out


def simulate_iso(path: str, profile: MachineProfile | None = None) -> list[list[tuple[float, float]]]:
    """Re-read a file produced by write_iso: returns tool-down polylines (for verification)."""
    profile = profile or MachineProfile()
    cuts, cur, pos, down = [], None, (0.0, 0.0), False
    for ln in open(path, encoding="ascii"):
        ln = ln.strip()
        m = re.match(rf"^({profile.rapid}|{profile.feed})\s+X(-?[\d.]+)\s+Y(-?[\d.]+)", ln)
        if m:
            pos = (float(m.group(2)), float(m.group(3)))
            if down and m.group(1) == profile.feed:
                cur.append(pos)
        elif ln == profile.tool_down:
            down, cur = True, [pos]
        elif ln == profile.tool_up:
            down = False
            if cur and len(cur) > 1:
                cuts.append(cur)
            cur = None
    return cuts
