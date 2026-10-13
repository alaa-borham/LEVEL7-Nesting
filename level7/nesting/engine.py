"""Nesting engine: NFP-based bottom-left placement + order optimisation with restarts.

Strategy
--------
1. Every piece copy becomes a ``NestItem`` with its search polygon (outward
   approximation of the cut contour grown by spacing/2, see geometry.search_polygon)
   and a list of allowed rotations derived from the grain line.
2. ``greedy`` places items in a given order. For each item and allowed rotation the
   feasible region = inner-fit rectangle minus union of NFPs with all placed items.
   Candidate positions are the vertices of that region; the best candidate minimises
   (resulting marker length, x, y).
3. ``NestEngine.run`` repeats ``greedy`` with mutated orders (seeded RNG, swap/insert
   moves, periodic restarts) until the time limit or a stop request and keeps the best
   complete solution. Results are geometric; global optimality is never claimed.

The engine never alters piece geometry; the only scaling is the shrinkage the user sets on the fabric
(FabricSettings.shrink_x / shrink_y), applied in marker axes and recorded on every placement (sx, sy).
Directional buffers (buffer_x / buffer_y) grow the search shapes only. Pieces that cannot fit the usable
width in any allowed orientation are reported as unplaced with a reason.
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field

import pyclipper

from .. import matching
from ..geometry import bbox, search_polygon, transform_points
from ..model import FabricSettings, LayType, NestSettings, Piece, Placement, Project
from .nfp import NFP_SHRINK, SCALE, feasible_region, nfp, shrink, to_int, translate

MODE_TIME = {"fast": 5.0, "balanced": 30.0, "long": 120.0}
CONTACT_MM = NFP_SHRINK / SCALE    # search polygons grow by this, NFPs shrink by it (see nfp.NFP_SHRINK)



@dataclass
class NestItem:
    uid: str
    piece_uid: str
    size: str
    bundle: int
    mirrored: bool
    rotations: list[float]
    cut: list[tuple[float, float]]                 # original cut contour (local coords)
    search: list[tuple[float, float]] = field(default_factory=list)
    deviation: float = 0.0
    pinned: Placement | None = None
    label: str = ""
    # plaid matching: (match x, match y, anchor (pattern coords), target x, target y, repeat x, repeat y)
    match: tuple | None = None

    @property
    def shape_key(self):
        return (self.piece_uid, self.size, self.mirrored)


@dataclass
class Unplaced:
    item_uid: str
    piece_uid: str
    size: str
    mirrored: bool
    reason: str


@dataclass
class NestResult:
    placements: list[Placement]
    unplaced: list[Unplaced]
    length: float
    evaluations: int = 0
    elapsed: float = 0.0
    seed: int = 0
    stopped: bool = False
    history: list[tuple[float, float]] = field(default_factory=list)  # (time, length)


def grain_rotations(piece: Piece, mirrored: bool, settings: NestSettings) -> tuple[list[float], str | None]:
    """Rotations that put the grain line parallel to the marker length (x axis)."""
    ga = piece.grain_angle
    if ga is None:
        return [], "grain direction unknown - define it for this piece"
    # base: the copy's grain (pattern top end) points along +x. A mirrored copy (x -> -x) has its grain at
    # 180 - ga; taking that modulo 180 lost the direction for ga = 0 (mirrored copies ended up turned 180°,
    # wrong for one-way fabric).
    base = ((ga - 180.0) if mirrored else -ga) % 360.0
    rots = [base]
    if settings.allow_rotation_180 and 180.0 in piece.allowed_rotations:
        rots.append((base + 180.0) % 360.0)
    if settings.allow_rotation_90:
        rots += [(base + 90.0) % 360.0, (base + 270.0) % 360.0]
    out = []
    for r in rots:
        r = round(r, 6) % 360.0
        if r not in out:
            out.append(r)
    return out, None


def _rescaled(pl: Placement, fabric: FabricSettings, project: Project) -> Placement:
    """A pinned copy with the fabric's current shrinkage, kept at the same spot (its lower-left corner)."""
    from dataclasses import replace
    sx, sy = fabric.scale
    if abs(pl.sx - sx) < 1e-12 and abs(pl.sy - sy) < 1e-12:
        return pl
    out = replace(pl, sx=sx, sy=sy)
    try:
        cut = project.piece(pl.piece_uid).sizes[pl.size].cut
    except KeyError:
        return out
    a = bbox(transform_points(cut, pl.rotation, pl.mirrored, pl.x, pl.y, pl.sx, pl.sy))
    b = bbox(transform_points(cut, out.rotation, out.mirrored, out.x, out.y, sx, sy))
    out.x += a[0] - b[0]
    out.y += a[1] - b[1]
    return out


def _match_rule(piece: Piece, size: str, fabric: FabricSettings, warnings: list):
    if not matching.active(piece, fabric):
        return None
    a = matching.anchor(piece, size)
    if a is None:
        msg = f"{piece.name} {size}: match point not found in this size - not matched"
        if msg not in warnings:
            warnings.append(msg)
        return None
    return (*matching.rules(piece, fabric), a, *matching.targets(fabric, piece), fabric.repeat_x, fabric.repeat_y)


def items_from_placements(project: Project, placements: list[Placement], fabric: FabricSettings,
                          settings: NestSettings) -> tuple[list[NestItem], list[Unplaced], list[str]]:
    """Re-nest exactly these copies (the pieces left in a marker); pinned ones keep their spot."""
    items, unplaced, warnings = [], [], []
    for pl in placements:
        piece = project.piece(pl.piece_uid)
        g = piece.sizes.get(pl.size)
        if g is None:
            unplaced.append(Unplaced(pl.uid, piece.uid, pl.size, pl.mirrored, f"size {pl.size} geometry not available"))
            continue
        rots, err = grain_rotations(piece, pl.mirrored, settings)
        if err:
            unplaced.append(Unplaced(pl.uid, piece.uid, pl.size, pl.mirrored, err))
            continue
        it = NestItem(pl.uid, piece.uid, pl.size, pl.bundle, pl.mirrored, rots, g.cut,
                      label=f"{piece.name} {pl.size}{' (M)' if pl.mirrored else ''} #{pl.bundle}",
                      match=_match_rule(piece, pl.size, fabric, warnings))
        if pl.pinned:
            it.pinned = _rescaled(pl, fabric, project)
        items.append(it)
    return items, unplaced, warnings


def build_items(project: Project, sizes: dict[str, int], counts: dict[str, tuple[int, int]],
                fabric: FabricSettings, settings: NestSettings, pinned: list[Placement] | None = None,
                material: str | None = None, excluded=None) -> tuple[list[NestItem], list[Unplaced], list[str]]:
    """Expand the cut order into individual piece copies (``excluded``: (size, bundle) rows left out)."""
    excluded = {(s, int(b)) for s, b in (excluded or [])}
    items: list[NestItem] = []
    unplaced: list[Unplaced] = []
    warnings: list[str] = []
    if any(abs(pl.sx - fabric.scale[0]) > 1e-12 or abs(pl.sy - fabric.scale[1]) > 1e-12 for pl in (pinned or [])):
        warnings.append("pinned pieces were placed with a different shrinkage: they keep their spot but change size "
                        "- unpin them if they now overlap")
    pinned = [_rescaled(pl, fabric, project) for pl in (pinned or [])]
    taken = {pl.uid for pl in pinned}           # new copies must never reuse a pinned placement's id
    uid_counter = 0
    for piece in project.pieces:
        n, m = counts.get(piece.uid, (0, 0))
        if n == 0 and m == 0:
            continue
        if material and piece.material and piece.material != material:
            continue
        if fabric.lay_type in (LayType.FACE_TO_FACE, LayType.FOLDED):
            k = max(n, m)
            if n != m:
                warnings.append(f"{piece.name}: lay type {fabric.lay_type.value} produces {k} normal + {k} "
                                f"mirrored per garment (requested {n}+{m})")
            n, m = k, 0   # each placement yields a mirrored partner on the second ply
        for size, qty in sizes.items():
            if qty <= 0:
                continue
            if piece.model and not size.startswith(piece.model + ":"):
                continue                     # several models in one session: sizes belong to their own model
            if size not in piece.sizes:
                unplaced.append(Unplaced("", piece.uid, size, False, f"size {size} geometry not available"))
                continue
            g = piece.sizes[size]
            match_rule = _match_rule(piece, size, fabric, warnings)
            for bundle in range(1, qty + 1):
                if (size, bundle) in excluded:
                    continue
                for mirrored, copies in ((False, n), (True, m)):
                    for _ in range(copies):
                        uid_counter += 1
                        while f"i{uid_counter}" in taken:
                            uid_counter += 1
                        rots, err = grain_rotations(piece, mirrored, settings)
                        uid = f"i{uid_counter}"
                        if err:
                            unplaced.append(Unplaced(uid, piece.uid, size, mirrored, err))
                            continue
                        it = NestItem(uid, piece.uid, size, bundle, mirrored, rots, g.cut,
                                      label=f"{piece.name} {size}{' (M)' if mirrored else ''} #{bundle}",
                                      match=match_rule)
                        for pl in pinned:
                            if pl.piece_uid == piece.uid and pl.size == size and pl.mirrored == mirrored \
                                    and pl.bundle == bundle and pl.placed and getattr(pl, "_used", False) is False:
                                it.pinned = pl
                                it.uid = pl.uid
                                pl._used = True  # type: ignore[attr-defined]
                                break
                        items.append(it)
    for pl in pinned:
        if hasattr(pl, "_used"):
            del pl._used
    return items, unplaced, warnings


class _Halt(Exception):
    """Stop pressed or time limit reached in the middle of placing a piece."""


HALT_REASON = "not placed: nesting stopped / time limit reached before this piece - give more time or nest again"


class NestEngine:
    def __init__(self, items: list[NestItem], fabric: FabricSettings, settings: NestSettings,
                 progress=None, stop_event: threading.Event | None = None):
        self.items = items
        self.fabric = fabric
        self.settings = settings
        self.progress = progress
        self.stop_event = stop_event or threading.Event()
        self._deadline: float | None = None     # monotonic time the search must end (run())
        self._oriented: dict = {}
        self._nfp_cache: dict = {}
        # directional buffers grow the shapes by ex / ey on each side; the usable area grows by the same amount
        # so the buffer only acts between pieces, not against the margins
        self.ex, self.ey = max(0.0, fabric.buffer_x) / 2.0, max(0.0, fabric.buffer_y) / 2.0
        self.sx, self.sy = fabric.scale
        self.y0 = fabric.margin_left - self.ey
        self.y1 = fabric.margin_left + fabric.usable_width + self.ey
        self.x0 = fabric.margin_start - self.ex
        # length bound without a max length: every copy in a row, measured on its grown search shape
        total = sum(max(self.oriented(it, it.rotations[0] if it.rotations else 0.0)[3:5]) for it in items)
        self.xmax = ((fabric.max_length - fabric.margin_end) if fabric.max_length else
                     fabric.margin_start + total * 1.2 + 1000.0) + self.ex

    key_mode = "length_x_y"

    def _key(self, newlen, x, y, wi):
        if self.key_mode == "length_right_y":
            return (round(newlen, 2), x + wi, y)
        if self.key_mode == "length_band":
            return (round(newlen, 2), (x + wi) // (20 * SCALE), y, x)
        return (round(newlen, 2), x, y)

    # -- geometry preparation ------------------------------------------------------
    def oriented(self, it: NestItem, rot: float):
        key = (it.shape_key, rot)
        o = self._oriented.get(key)
        if o is None:
            pts, _ = search_polygon(transform_points(it.cut, rot, it.mirrored, sx=self.sx, sy=self.sy),
                                    self.fabric.spacing + 2 * CONTACT_MM, self.settings.curve_tolerance,
                                    (self.ex, self.ey))
            bx0, by0, bx1, by1 = bbox(pts)
            norm = [(x - bx0, y - by0) for x, y in pts]
            ip = to_int(norm)
            o = (ip, bx0, by0, bx1 - bx0, by1 - by0)
            self._oriented[key] = o
        return o

    def nfp_rel(self, a: NestItem, ra: float, b: NestItem, rb: float):
        key = (a.shape_key, ra, b.shape_key, rb)
        r = self._nfp_cache.get(key)
        if r is None:
            r = shrink(nfp(self.oriented(a, ra)[0], self.oriented(b, rb)[0]))
            self._nfp_cache[key] = r
        return r

    # -- greedy placement ----------------------------------------------------------
    def _halted(self) -> bool:
        return self.stop_event.is_set() or (self._deadline is not None and time.monotonic() > self._deadline)

    def greedy(self, order: list[int], abort_len: float | None = None, ignore_stop: bool = False,
               rot_pref: dict | None = None, partial: bool = False):
        """Bottom-left fill in ``order``. Stop / time limit: None, or with ``partial`` the pieces placed so far
        (the others reported as not placed) - a big job's first layout can take longer than the time given."""
        placed: list[tuple[NestItem, float, tuple[int, int]]] = []
        result: dict[int, tuple[float, tuple[int, int]]] = {}
        failed: dict[int, str] = {}
        length = self.x0
        for idx, it in enumerate(self.items):
            if it.pinned is not None:
                pl = it.pinned
                ip, bx0, by0, w, h = self.oriented(it, pl.rotation)
                t = (int(round((pl.x + bx0) * SCALE)), int(round((pl.y + by0) * SCALE)))
                placed.append((it, pl.rotation, t))
                result[idx] = (pl.rotation, t)
                length = max(length, (t[0] / SCALE) + w)
        halted = False
        for idx in order:
            it = self.items[idx]
            if it.pinned is not None:
                continue
            if halted or (self._halted() and not ignore_stop):
                if not partial:
                    return None
                halted = True
                failed[idx] = HALT_REASON
                continue
            best = None
            if rot_pref is not None and idx in rot_pref:
                pref = it.rotations[rot_pref[idx] % len(it.rotations)]
                groups = [[pref], [r for r in it.rotations if r != pref]]
            else:
                groups = [it.rotations]
            try:
                for group in groups:
                    if best is not None:
                        break
                    for rot in group:
                        best = self._best_position(it, rot, placed, length, best, not ignore_stop)
            except _Halt:
                if not partial:
                    return None
                halted = True
                failed[idx] = HALT_REASON
                continue
            if best is None:
                fits = any(self.oriented(it, r)[4] <= (self.y1 - self.y0) + 1e-6 for r in it.rotations)
                failed[idx] = ("no free position within length limit" if fits else
                               f"does not fit usable width {self.fabric.usable_width:.1f} mm in allowed orientations")
                continue
            _, rot, t, w = best
            placed.append((it, rot, t))
            result[idx] = (rot, t)
            length = max(length, t[0] / SCALE + w)
            if abort_len is not None and length > abort_len + 1e-9:
                return ("abort", length)
        return (result, failed, length)

    def _best_position(self, it, rot, placed, length, best, halt=True):
        if it.match is not None:
            return self._best_matched(it, rot, placed, length, best)
        ip, bx0, by0, w, h = self.oriented(it, rot)
        if h > (self.y1 - self.y0) + 1e-6:
            return best
        xa, xb = int(math.ceil(self.x0 * SCALE)), int(math.floor((self.xmax - w) * SCALE))
        ya, yb = int(math.ceil(self.y0 * SCALE)), int(math.floor((self.y1 - h) * SCALE))
        if xb < xa or yb < ya:
            return best
        rect = [(xa, ya), (xb, ya), (xb, yb), (xa, yb)]
        forb = []
        for k, (pit, prot, pt) in enumerate(placed):
            if halt and k % 16 == 15 and self._halted():      # Stop answers within a fraction of a second
                raise _Halt()
            forb.extend(translate(self.nfp_rel(pit, prot, it, rot), pt[0], pt[1]))
        region = feasible_region(rect, forb)
        wi = int(round(w * SCALE))
        for path in region:
            for (x, y) in path:
                newlen = max(length, (x + wi) / SCALE)
                key = self._key(newlen, x, y, wi)
                if best is None or key < best[0]:
                    best = (key, rot, (x, y), w)
        return best

    def _best_matched(self, it, rot, placed, length, best):
        """Plaid matching: only positions where the anchor lies on its pattern line(s)."""
        from shapely.geometry import LineString, Point, Polygon
        from shapely.ops import unary_union
        from shapely.prepared import prep
        ip, bx0, by0, w, h = self.oriented(it, rot)
        if h > (self.y1 - self.y0) + 1e-6:
            return best
        xa, xb = int(math.ceil(self.x0 * SCALE)), int(math.floor((self.xmax - w) * SCALE))
        ya, yb = int(math.ceil(self.y0 * SCALE)), int(math.floor((self.y1 - h) * SCALE))
        if xb < xa or yb < ya:
            return best
        rect = [(xa, ya), (xb, ya), (xb, yb), (xa, yb)]
        forb = []
        for (pit, prot, pt) in placed:
            forb.extend(translate(self.nfp_rel(pit, prot, it, rot), pt[0], pt[1]))
        paths = feasible_region(rect, forb)
        outer = [Polygon(p) for p in paths if len(p) >= 3 and pyclipper.Orientation(p)]
        holes = [Polygon(p) for p in paths if len(p) >= 3 and not pyclipper.Orientation(p)]
        if not outer:
            return best
        region = unary_union(outer)
        if holes:
            region = region.difference(unary_union(holes))
        if region.is_empty:
            return best
        pr = prep(region)
        rx, ry, (ax, ay), tx, ty, rpx, rpy = it.match
        (mx, my), = transform_points([(ax, ay)], rot, it.mirrored, sx=self.sx, sy=self.sy)
        # translation t (search-shape frame) puts the anchor at t/SCALE - b0 + m: solve for the pattern lines
        cx, cy = (tx - mx + bx0) * SCALE, (ty - my + by0) * SCALE
        wi = int(round(w * SCALE))

        def lines(c, lo, hi, rep):
            r = rep * SCALE
            k = math.ceil((lo - c) / r)
            v = c + k * r
            while v <= hi:
                yield int(round(v))
                v += r

        def consider(x, y):
            nonlocal best
            newlen = max(length, (x + wi) / SCALE)
            key = self._key(newlen, x, y, wi)
            if best is None or key < best[0]:
                best = (key, rot, (x, y), w)

        minx, miny, maxx, maxy = region.bounds
        if rx:
            for x in lines(cx, max(xa, minx), min(xb, maxx), rpx):   # first column that fits is the shortest
                if ry:
                    ys = [y for y in lines(cy, max(ya, miny), min(yb, maxy), rpy) if pr.covers(Point(x, y))]
                    if ys:
                        consider(x, ys[0])
                        break
                else:
                    seg = region.intersection(LineString([(x, miny - 1), (x, maxy + 1)]))
                    if not seg.is_empty:
                        consider(x, int(math.ceil(seg.bounds[1])))
                        break
        elif ry:
            for y in lines(cy, max(ya, miny), min(yb, maxy), rpy):
                seg = region.intersection(LineString([(minx - 1, y), (maxx + 1, y)]))
                if not seg.is_empty:
                    consider(int(math.ceil(seg.bounds[0])), y)
        return best

    def to_result(self, sol, evaluations, elapsed, stopped, history) -> NestResult:
        result, failed, length = sol
        pls = []
        unpl = []
        for idx, it in enumerate(self.items):
            if idx in result:
                rot, t = result[idx]
                ip, bx0, by0, w, h = self.oriented(it, rot)
                pl = Placement(uid=it.uid, piece_uid=it.piece_uid, size=it.size, bundle=it.bundle,
                               x=t[0] / SCALE - bx0, y=t[1] / SCALE - by0, rotation=rot, mirrored=it.mirrored,
                               pinned=it.pinned is not None, sx=self.sx, sy=self.sy)
                pls.append(pl)
            else:
                unpl.append(Unplaced(it.uid, it.piece_uid, it.size, it.mirrored, failed.get(idx, "not placed")))
        return NestResult(pls, unpl, max(length - self.ex, self.fabric.margin_start) + self.fabric.margin_end, evaluations, elapsed, self.settings.seed,
                          stopped, history)

    # -- optimisation loop ---------------------------------------------------------
    def initial_orders(self) -> list[list[int]]:
        idx = [i for i, it in enumerate(self.items) if it.pinned is None]

        def area(i):
            b = bbox(self.items[i].cut)
            return (b[2] - b[0]) * (b[3] - b[1])

        def longest(i):
            b = bbox(self.items[i].cut)
            return max(b[2] - b[0], b[3] - b[1])
        return [sorted(idx, key=area, reverse=True), sorted(idx, key=longest, reverse=True)]

    def run(self) -> NestResult:
        """Genetic search over (order, preferred rotation) with elitism; keeps the best valid layout."""
        t0 = time.monotonic()
        limit = self.settings.time_limit or MODE_TIME.get(self.settings.mode, 30.0)
        if getattr(self.settings, "hard_time", True):
            self._deadline = t0 + limit
        rng = random.Random(self.settings.seed)
        free = [i for i, it in enumerate(self.items) if it.pinned is None]
        evaluations = 0
        history: list[tuple[float, float]] = []
        best = None

        def fitness(sol):
            return (len(sol[1]), sol[2])

        def report(sol):
            if self.progress:
                self.progress({"elapsed": time.monotonic() - t0, "evaluations": evaluations,
                               "length": sol[2] - self.ex + self.fabric.margin_end, "unplaced": len(sol[1]),
                               "result": self.to_result(sol, evaluations, time.monotonic() - t0, False, history),
                               "final": False})

        def evaluate(ind, ignore_stop=False, abort=None):
            nonlocal evaluations, best
            order, rots = ind
            # no layout yet: a stopped / timed-out first pass still returns the pieces it placed
            sol = self.greedy(order, abort_len=abort, ignore_stop=ignore_stop, rot_pref=rots, partial=best is None)
            evaluations += 1
            if sol is None:
                return None
            if isinstance(sol[0], str):
                return (len(free) + 1, sol[1])
            if best is None or fitness(sol) < fitness(best[0]):
                best = (sol, ind)
                history.append((time.monotonic() - t0, sol[2]))
                report(sol)
            return fitness(sol)

        def rand_rots():
            return {i: rng.randrange(max(1, len(self.items[i].rotations))) for i in free}

        seeds = self.initial_orders()
        pop: list[tuple[tuple, tuple]] = []
        for k, order in enumerate(seeds):
            ind = (order, {i: 0 for i in free})
            f = evaluate(ind)                  # Stop works at once, even before a first complete layout
            if f is None:
                break
            pop.append((f, ind))
        size = 10 if self.settings.mode != "fast" else 6

        def mutate(ind, rate=0.12):
            order, rots = list(ind[0]), dict(ind[1])
            for a in range(len(order)):
                if rng.random() < rate:
                    b = min(len(order) - 1, a + 1 + int(rng.random() * 3))
                    order[a], order[b] = order[b], order[a]
            for i in rots:
                if rng.random() < rate:
                    rots[i] = rng.randrange(max(1, len(self.items[i].rotations)))
            return (order, rots)

        def crossover(p1, p2):
            n = len(p1[0])
            if n < 2:
                return p1
            a, b = sorted(rng.sample(range(n), 2))
            mid = p1[0][a:b]
            taken = set(mid)
            rest = [g for g in p2[0] if g not in taken]
            order = rest[:a] + mid + rest[a:]
            rots = {i: (p1[1][i] if rng.random() < 0.5 else p2[1][i]) for i in p1[1]}
            return (order, rots)

        while pop and len(pop) < size and not self.stop_event.is_set() and time.monotonic() - t0 < limit:
            base = pop[0][1]
            ind = mutate((base[0], rand_rots()), 0.3)
            f = evaluate(ind)
            if f is None:
                break
            pop.append((f, ind))
        while pop and len(free) > 1 and not self.stop_event.is_set() and time.monotonic() - t0 < limit:
            if self.settings.attempts and evaluations >= self.settings.attempts:
                break
            pop.sort(key=lambda x: x[0])
            nxt = pop[:2]
            worst = pop[-1][0]
            while len(nxt) < size and not self.stop_event.is_set() and time.monotonic() - t0 < limit:
                def pick():
                    a, b = rng.sample(pop, 2) if len(pop) > 1 else (pop[0], pop[0])
                    return a[1] if a[0] <= b[0] else b[1]
                child = crossover(pick(), pick()) if rng.random() < 0.8 else pick()
                child = mutate(child)
                abort = worst[1] if worst[0] == 0 else None
                f = evaluate(child, abort=abort)
                if f is None:
                    break
                nxt.append((f, child))
            pop = nxt
        stopped = self.stop_event.is_set()
        if best is None:                       # stopped before the first complete layout: nothing placed
            res = NestResult([], [Unplaced(it.uid, it.piece_uid, it.size, it.mirrored, "stopped")
                                  for it in self.items if it.pinned is None],
                             self.fabric.margin_start + self.fabric.margin_end, evaluations,
                             time.monotonic() - t0, self.settings.seed, True, history)
            if self.progress:
                self.progress({"elapsed": res.elapsed, "evaluations": evaluations, "length": res.length,
                               "unplaced": len(res.unplaced), "result": res, "final": True})
            return res
        res = self.to_result(best[0], evaluations, time.monotonic() - t0, stopped, history)
        if self.progress:
            self.progress({"elapsed": res.elapsed, "evaluations": evaluations, "length": res.length,
                           "unplaced": len(res.unplaced), "result": res, "final": True})
        return res
