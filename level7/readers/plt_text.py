"""Reading the texts a plotter file draws as strokes (GRAFIS plots sizes like "44" with a single-stroke font,
not as HP-GL labels).

Small strokes inside a piece are grouped into texts; each text is tried in the four reading directions, cut into
characters and every character compared with the single-stroke font (letters, digits, "-", "/" ...). A text is
accepted only when every character matches well in one direction; otherwise it stays unread (None).
"""
from __future__ import annotations

import math
import re

import numpy as np

from ..exporters.strokefont import G

GLYPH_MAX = 30.0          # mm: strokes larger than this are not text
MATCH_MAX = 0.75          # mean distance (font grid units, cap height = 6) for a character to count as read
STEP = 0.35


def _sample(strokes, step=STEP):
    out = []
    for s in strokes:
        if len(s) == 1:
            out.append(s[0])
        for (ax, ay), (bx, by) in zip(s, s[1:]):
            n = max(1, int(math.hypot(bx - ax, by - ay) / step))
            out.extend((ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(n))
        out.append(s[-1])
    return out


TEMPLATES = {}
for _ch, _st in G.items():
    if _st:
        _pts = _sample(_st)
        TEMPLATES[_ch] = (np.array(_pts), max(p[0] for p in _pts) - min(p[0] for p in _pts),
                          min(p[0] for p in _pts))


def _chamfer(a, b):
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    return max(d.min(1).mean(), d.min(0).mean())


def _ext(s):
    xs, ys = [p[0] for p in s], [p[1] for p in s]
    return min(xs), min(ys), max(xs), max(ys)


def is_glyph_stroke(s) -> bool:
    x0, y0, x1, y1 = _ext(s)
    return max(x1 - x0, y1 - y0) <= GLYPH_MAX


def clusters(strokes):
    """Group text strokes that lie close together (characters of one text)."""
    boxes = [_ext(s) for s in strokes]
    parent = list(range(len(strokes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(strokes)):
        for j in range(i + 1, len(strokes)):
            a, b = boxes[i], boxes[j]
            gap = max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3], 0.0)
            size = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1])
            if gap <= 0.9 * size:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i, s in enumerate(strokes):
        groups.setdefault(find(i), []).append(s)
    return list(groups.values())


def _rotate(strokes, rot):
    c, s = round(math.cos(math.radians(rot))), round(math.sin(math.radians(rot)))
    return [[(c * x + s * y, -s * x + c * y) for x, y in st] for st in strokes]   # turned back by rot


def _read_chars(strokes):
    """(text, worst score) of a text already turned to read left to right, or None."""
    allp = [p for s in strokes for p in s]
    v0 = min(p[1] for p in allp)
    H = max(p[1] for p in allp) - v0
    if H < 1.0:
        return None
    k = 6.0 / H
    # characters: strokes overlapping along the reading direction
    items = sorted(((min(p[0] for p in s), max(p[0] for p in s), s) for s in strokes), key=lambda t: t[0])
    chars: list[list] = []
    for u0, u1, s in items:
        if chars and u0 <= chars[-1][1] + 0.12 * H:
            chars[-1][1] = max(chars[-1][1], u1)
            chars[-1][2].append(s)
        else:
            chars.append([u0, u1, [s]])
    text, worst = "", 0.0
    for i, (u0, u1, sts) in enumerate(chars):
        if i and u0 - chars[i - 1][1] > 0.9 * H:
            text += " "
        pts = (np.array(_sample(sts, STEP / k)) - (u0, v0)) * k
        wg = (u1 - u0) * k
        best = (9.0, "?")
        for ch, (tp, wt, tx0) in TEMPLATES.items():
            if ch == " ":
                continue
            if wg > 0.5 and wt > 0.5:
                f = wt / wg
                if not 0.45 <= f <= 2.2:
                    continue
                q = pts * (f, 1.0) + (tx0, 0.0)
            elif wg <= 0.5 and wt <= 0.5:
                q = pts + (tx0, 0.0)
            else:
                continue
            d = _chamfer(q, tp)
            if d < best[0]:
                best = (d, ch)
        if best[0] > MATCH_MAX:
            return None
        text += best[1]
        worst = max(worst, best[0])
    return text, worst


_CACHE: dict = {}


def candidates(strokes):
    """Readings of one text cluster as [(score, rotation deg, text)], best first. A marker repeats its texts
    (the same size on hundreds of pieces): readings are kept by shape."""
    x0 = min(p[0] for s in strokes for p in s)
    y0 = min(p[1] for s in strokes for p in s)
    key = tuple(sorted(tuple((round((x - x0) * 5), round((y - y0) * 5)) for x, y in s) for s in strokes))
    if key in _CACHE:
        return _CACHE[key]
    if len(_CACHE) > 5000:
        _CACHE.clear()
    _CACHE[key] = found = _candidates(strokes)
    return found


def _candidates(strokes):
    found = []
    for rot in (0, 90, 180, 270):
        r = _read_chars(_rotate(strokes, rot))
        if r is not None:
            found.append((r[1], rot, r[0]))
    return sorted(found)


_SIZE = re.compile(r"^(?:[1-9]\d{0,2}(?:[-/][1-9]\d{0,2})?|\d?X{0,4}[SL]|M|[1-9]\d{0,2}[A-Z]{0,2}|"
                   r"(?:\d?X{0,4}[SL]|M)[-/](?:\d?X{0,4}[SL]|M))$")


def size_like(t: str) -> bool:
    """"44", "52/54", "XL", "3XL", "M-L", "38R" - not "09", "SX", "6I"."""
    return bool(_SIZE.match(t.strip()))


def ambiguous(cands, tie=0.1) -> bool:
    return len(cands) > 1 and cands[1][0] <= cands[0][0] + tie and cands[1][2] != cands[0][2]


def choose(cands, prefer=(), tie=0.1):
    """(text, rotation) of the best reading. Readings within ``tie`` of the best (a text that also reads turned
    180 deg: 6 / 9, XS / SX) are decided by: looks like a size, then the first rotation in ``prefer``."""
    if not cands:
        return None, None
    near = [c for c in cands if c[0] <= cands[0][0] + tie]
    sized = [c for c in near if size_like(c[2])] or near
    for r in prefer:
        hit = next((c for c in sized if c[1] == r), None)
        if hit is not None:
            return hit[2], hit[1]
    return sized[0][2], sized[0][1]


def read_text(strokes, prefer=()):
    """(text, rotation deg) of one text cluster, or (None, None)."""
    return choose(candidates(strokes), prefer)
