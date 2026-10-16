"""ISO (G-code style) cutting-file post-processor.

Profiles
* ``bullmer_grafis_profile()`` — Bullmer cutter, reproducing GRAFIS' "Bullmer-Cutter (typical)" output
  (reference: samples/reference/Neay blue pants-44-1500.iso; see docs/BULLMER_ISO.md). Verified at file
  level against that reference; a test cut on the machine is still required (``device_tested``).
* default (UNCONFIGURED) — only a DIAGNOSTIC PREVIEW with generic codes, marked not for production.

This module never talks to a machine.
"""
from __future__ import annotations

import json
import os
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
    order: str = "nearest"               # nearest / as_is / bands
    dialect: str = "gcode"               # "gcode" (diagnostic) | "bullmer_grafis"
    units_per_mm: float = 10.0           # bullmer_grafis: 0.1 mm integer coordinates
    band_width: float = 400.0            # cut order: vertical bands along the length (mm), bottom-up
    device_tested: bool = False          # set True only after a test cut on the machine
    min_segment: float = 0.0             # bullmer_grafis: drop vertices closer than this to the last kept one

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def from_dict(cls, raw: dict):
        """Settings saved by another LEVEL7 version: unknown keys are left out (they would refuse to load)."""
        from dataclasses import fields
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (raw or {}).items() if k in names})


class NotConfigured(Exception):
    pass


def bullmer_grafis_profile() -> MachineProfile:
    return MachineProfile(name="Bullmer-Cutter (GRAFIS 'typical' compatible)", verified=True,
                          dialect="bullmer_grafis", units_per_mm=10.0, order="bands", min_segment=2.0,
                          layers_cut=["CUT"], layers_notch=["NOTCH"], layers_drill=[])


def iecho_profile() -> MachineProfile:
    """IECHO cutter: the user feeds it the same file that GRAFIS writes for the Bullmer (user statement).
    Same writer as bullmer_grafis_profile(); needs its own test cut on the IECHO."""
    p = bullmer_grafis_profile()
    p.name = "IECHO (same file as Bullmer - GRAFIS 'typical')"
    return p


ISO_PRESETS = {"unconfigured": MachineProfile, "bullmer_grafis": bullmer_grafis_profile, "iecho": iecho_profile}


def _cut_sequence(path, notches, corners, min_segment=0.0):
    """Clockwise contour starting at the corner nearest the bbox top-right corner, with notch plunges.
    Returns a list of ("cut", point) / ("lift", None) / ("move", point) / ("down", None) actions."""
    import math
    pts = list(path.points)
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area > 0:            # make clockwise (marker coordinates, y up)
        pts = pts[::-1]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    tr = (max(xs), max(ys))
    cands = corners or pts
    target = min(cands, key=lambda c: math.dist(c, tr))
    i0 = min(range(len(pts)), key=lambda i: math.dist(pts[i], target))
    pts = pts[i0:] + pts[:i0]
    # insert notch bases into the point list, remember plunge positions
    seq = [(p, None) for p in pts]
    for base, tip in notches:
        best = None
        n = len(seq)
        for i in range(n):
            a, b = seq[i][0], seq[(i + 1) % n][0]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((base[0] - a[0]) * dx + (base[1] - a[1]) * dy) / L2))
            d = math.dist((a[0] + t * dx, a[1] + t * dy), base)
            if best is None or d < best[0]:
                best = (d, i, t)
        if best is None or best[0] > 0.01:
            continue
        _, i, t = best
        if t <= 1e-9:
            seq[i] = (seq[i][0], tip)
        elif t >= 1 - 1e-9:
            j = (i + 1) % n
            seq[j] = (seq[j][0], tip)
        else:
            seq.insert(i + 1, (base, tip))
    if min_segment > 0:
        # GRAFIS (Bullmer output) drops vertices closer than min_segment to the last kept vertex; a notch on
        # a dropped vertex is cut from the last kept vertex (measured on the reference file: kept >= 2.3 mm,
        # dropped <= 1.73 mm).
        kept = [list(seq[0])]
        for p, tip in seq[1:]:
            if math.dist(p, kept[-1][0]) < min_segment:
                if tip is not None and kept[-1][1] is None:
                    kept[-1][1] = tip
                continue
            kept.append([p, tip])
        while len(kept) > 3 and kept[-1][1] is None and math.dist(kept[-1][0], kept[0][0]) < min_segment:
            kept.pop()
        seq = [tuple(k) for k in kept]
    acts = [("move", seq[0][0]), ("down", None)]
    start_tip = seq[0][1]
    for p, tip in seq[1:] + [(seq[0][0], start_tip)]:
        acts.append(("cut", p))
        if tip is not None:
            acts += [("cut", tip), ("lift", None), ("move", p), ("down", None)]
    acts.append(("lift", None))
    return acts


def _band_order(paths, band):
    def key(p):
        xs = [q[0] for q in p.points]
        ys = [q[1] for q in p.points]
        return (int(min(xs) // band), min(ys))
    order = sorted(paths, key=key)
    # a contour inside another (a hole / cut-out) is cut BEFORE its piece: once the outline is cut the piece is
    # loose and the hole would be cut in a moving part
    from shapely import STRtree
    from shapely.geometry import Polygon
    polys = [Polygon(p.points).buffer(0) for p in order]
    tree = STRtree(polys)
    host = {}
    for i, pg in enumerate(polys):
        outer = [int(j) for j in tree.query(pg, predicate="within") if int(j) != i and polys[int(j)].area > pg.area]
        if outer:
            host[i] = min(outer, key=lambda j: polys[j].area)       # the closest piece around it
    if not host:
        return order
    out = []
    for i, p in enumerate(order):
        if i in host:
            continue
        out.extend(order[k] for k in range(len(order)) if host.get(k) == i)
        out.append(p)
    out.extend(order[k] for k in host if host[k] in host)          # (a contour inside a hole: after it)
    return out


def _write_atomic(path: str, text: str):
    """Write the whole file or nothing (no half-written job on the cutter after an error)."""
    tmp = path + ".part"
    try:
        with open(tmp, "w", encoding="ascii", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _write_bullmer(scene: Scene, path: str, profile: MachineProfile, job_name: str) -> dict:
    u = profile.units_per_mm

    def xy(p):
        return f"X{int(round(p[0] * u))}Y{int(round(p[1] * u))}*"
    notches: dict = {}
    for p in scene.paths:
        if p.layer in profile.layers_notch and len(p.points) == 2:
            notches.setdefault(p.owner, []).append((p.points[0], p.points[1]))
    cuts = [p for p in scene.paths if p.layer in profile.layers_cut and p.closed and len(p.points) >= 3]
    cuts = _band_order(cuts, profile.band_width)
    # the controller header is ASCII only (Arabic marker names would break the file): keep printable ASCII
    name = "".join(ch for ch in job_name.upper() if 32 < ord(ch) < 127 and ch not in "*/") or "LEVEL7"
    lines = ["H1*G71*M70*D2*M15*", f"M20*{name}/L={scene.length / 1000:.2f}m/B={scene.width / 1000:.2f}m*"]
    stats = {"pieces": 0, "notches": 0}
    for k, c in enumerate(cuts, 1):
        lines += [f"N{k}*", "D2*M15*"]
        acts = _cut_sequence(c, notches.get(c.owner, []), c.corners, profile.min_segment)
        last = None
        for a, p in acts:
            if a in ("move", "cut"):
                cmd = xy(p)
                if cmd != last:          # never emit the current position again
                    lines.append(cmd)
                    last = cmd
            elif a == "down":
                lines.append("M14*")
            elif a == "lift":
                lines.append("M15*")
        stats["pieces"] += 1
        stats["notches"] += len(notches.get(c.owner, []))
    if lines[-1] == "M15*":
        lines[-1] = "M15*D4*M00*"
    else:                                # no pieces: still end the job
        lines.append("M15*D4*M00*")
    _write_atomic(path, "\r\n".join(lines) + "\r\n")
    stats["diagnostic"] = False
    stats["device_tested"] = profile.device_tested
    return stats


def _fmt(v, d):
    return f"{v:.{d}f}"


def write_iso(scene: Scene, path: str, profile: MachineProfile | None = None, diagnostic: bool = False,
              job_name: str = "LEVEL7") -> dict:
    profile = profile or MachineProfile()
    if profile.dialect == "bullmer_grafis" and profile.verified and not diagnostic:
        return _write_bullmer(scene, path, profile, job_name)
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
    _write_atomic(path, "\n".join(lines) + "\n")
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
    with open(path, encoding="ascii") as fh:
        text = fh.read()
    for ln in text.splitlines():
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
