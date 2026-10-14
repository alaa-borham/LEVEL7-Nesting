"""Run independent searches (different seeds) in worker processes and keep the best.

Uses the "spawn" start method (the only one on Windows) so behaviour is the same on
all platforms. A shared Event stops every worker; each worker always returns its
best complete layout.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time
from dataclasses import replace

from ..model import FabricSettings, NestSettings
from .engine import NestEngine, NestItem, NestResult


def _lower_priority():
    """Search processes run below normal priority so the desktop and the LEVEL7 window stay responsive."""
    try:
        if os.name == "nt":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                    BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(5)
    except Exception:
        pass


def _worker(items, fabric, settings, stop, q, wid):
    _lower_priority()
    def prog(d):
        try:
            q.put(("progress", wid, {k: v for k, v in d.items() if k != "final"}))
        except Exception:
            pass
    try:
        res = NestEngine(items, fabric, settings, progress=prog, stop_event=_EventProxy(stop)).run()
        q.put(("done", wid, res))
    except Exception as e:  # pragma: no cover - reported to caller
        q.put(("error", wid, repr(e)))


class _EventProxy:
    """threading.Event-like wrapper around a multiprocessing Event."""

    def __init__(self, ev):
        self.ev = ev

    def is_set(self):
        return self.ev.is_set()

    def set(self):
        self.ev.set()

    def clear(self):
        self.ev.clear()


def _better(a: NestResult | None, b: NestResult) -> bool:
    return a is None or (len(b.unplaced), b.length) < (len(a.unplaced), a.length)


def run_parallel(items: list[NestItem], fabric: FabricSettings, settings: NestSettings, workers: int | None = None,
                 progress=None, stop_event: threading.Event | None = None) -> NestResult:
    # one core is left free for the user interface
    workers = max(1, min(4, workers or (os.cpu_count() or 2) - 1))      # beyond 4 seeds the gain is small
    if workers == 1:
        return NestEngine(items, fabric, settings, progress=progress, stop_event=stop_event).run()
    ctx = mp.get_context("spawn")
    stop = ctx.Event()
    q = ctx.Queue()
    procs = []
    for k in range(workers):
        st = replace(settings, seed=settings.seed + k)
        p = ctx.Process(target=_worker, args=(items, fabric, st, stop, q, k), daemon=True)
        p.start()
        procs.append(p)
    best: NestResult | None = None
    done = 0
    errors = []
    evals = {}
    placing: dict = {}
    t0 = time.monotonic()
    limit = settings.time_limit + (5.0 if getattr(settings, "hard_time", False) else 60.0)
    while done < workers:
        if stop_event is not None and stop_event.is_set():
            stop.set()
        try:
            kind, wid, payload = q.get(timeout=0.2)
        except queue.Empty:
            # safety guard; without a hard time limit the first complete layout is waited for (a stop here
            # made every worker return a partial layout 60 s late)
            if time.monotonic() - t0 > limit and (best is not None or getattr(settings, "hard_time", False)):
                stop.set()
            if not any(p.is_alive() for p in procs) and q.empty():
                break
            continue
        if kind == "progress" and "placing" in payload:     # a worker's first layout, piece by piece
            if best is None and progress:
                placing[wid] = payload["placing"]
                progress({"elapsed": time.monotonic() - t0, "placing": max(placing.values()), "of": payload["of"],
                          "result": None, "final": False})
            continue
        if kind == "progress":
            evals[wid] = payload["evaluations"]
            r = payload.get("result")
            if r is not None and _better(best, r):
                best = r
                if progress:
                    progress({"elapsed": time.monotonic() - t0, "evaluations": sum(evals.values()),
                              "length": r.length, "unplaced": len(r.unplaced), "result": r, "final": False,
                              "worker": wid})
        elif kind == "done":
            done += 1
            evals[wid] = payload.evaluations
            if _better(best, payload):
                best = payload
        else:
            done += 1
            errors.append(payload)
    for p in procs:
        p.join(timeout=5)
    if best is None:
        # worker processes could not run (e.g. restricted environment): fall back to in-process search
        best = NestEngine(items, fabric, settings, progress=progress, stop_event=stop_event).run()
        return best
    best.evaluations = sum(evals.values())
    best.elapsed = time.monotonic() - t0
    best.stopped = stop.is_set() and (stop_event is not None and stop_event.is_set())
    if progress:
        progress({"elapsed": best.elapsed, "evaluations": best.evaluations, "length": best.length,
                  "unplaced": len(best.unplaced), "result": best, "final": True})
    return best
