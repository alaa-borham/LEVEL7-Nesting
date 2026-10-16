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


def _worker(items_path, fabric, settings, stop, q, wid):
    _lower_priority()
    import pickle
    with open(items_path, "rb") as fh:          # the pieces come in a file (see run_parallel)
        items = pickle.load(fh)
    def prog(d):
        if d.get("final"):           # the end result comes with "done" (a final report of a layout cut short
            return                   # was passed on as a "best length")
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
    import pickle
    import tempfile
    ctx = mp.get_context("spawn")
    stop = ctx.Event()
    q = ctx.Queue()
    procs = []
    # The pieces go to the workers in a file, not through process start: Windows hands start arguments over a
    # pipe the new process must read, and a big job blocked Process.start() for minutes when a process came up
    # slowly (antivirus scan of the program) or not at all - Stop could not get through (hang.log, 10/2026).
    fd, items_path = tempfile.mkstemp(prefix="level7_items_", suffix=".pkl")
    with os.fdopen(fd, "wb") as fh:
        pickle.dump(items, fh, protocol=pickle.HIGHEST_PROTOCOL)
    try:
        for k in range(workers):
            if stop_event is not None and stop_event.is_set():
                break
            st = replace(settings, seed=settings.seed + k)
            p = ctx.Process(target=_worker, args=(items_path, fabric, st, stop, q, k), daemon=True)
            p.start()
            procs.append(p)
        if not procs:
            ev = threading.Event()
            ev.set()
            return NestEngine(items, fabric, settings, stop_event=ev).run()
        return _collect(procs, workers, items, fabric, settings, progress, stop_event, stop, q)
    finally:
        try:
            os.remove(items_path)
        except OSError:
            pass


def _collect(procs, workers, items, fabric, settings, progress, stop_event, stop, q) -> NestResult:
    workers = len(procs)
    best: NestResult | None = None
    done = 0
    errors = []
    evals = {}
    placing: dict = {}
    t0 = time.monotonic()
    limit = settings.time_limit + (5.0 if getattr(settings, "hard_time", False) else 60.0)
    stop_since = None
    heard = False
    while done < workers:
        if stop_event is not None and stop_event.is_set():
            stop.set()
        if stop.is_set():
            stop_since = stop_since or time.monotonic()
            # a worker that does not answer within 3 s of the stop (busy in one long geometry call, or stuck)
            # is ended: the results already received are used - Stop never waits for it
            if time.monotonic() - stop_since > 3.0:
                for p in procs:
                    if p.is_alive():
                        p.terminate()
                break
        try:
            kind, wid, payload = q.get(timeout=0.2)
            heard = True
        except queue.Empty:
            # no worker has said anything in a minute (never came up / stuck): end them, search in-process
            if not heard and time.monotonic() - t0 > 60.0:
                for p in procs:
                    if p.is_alive():
                        p.terminate()
                break
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
        p.join(timeout=2)
        if p.is_alive():
            p.terminate()
    if errors:
        import logging
        logging.getLogger("level7").warning("nesting worker errors: %s", "; ".join(map(str, errors))[:2000])
    if best is None:
        if stop_event is not None and stop_event.is_set():   # the user stopped before any result: nothing placed
            ev = threading.Event()
            ev.set()
            return NestEngine(items, fabric, settings, stop_event=ev).run()
        # worker processes could not run, or came up too late (slow start, antivirus): search in-process in
        # the time that is left instead of returning an empty marker
        st = settings
        if getattr(settings, "hard_time", False):
            from dataclasses import replace
            st = replace(settings, time_limit=max(2.0, settings.time_limit - (time.monotonic() - t0)))
        return NestEngine(items, fabric, st, progress=progress, stop_event=stop_event).run()
    best.evaluations = sum(evals.values())
    best.elapsed = time.monotonic() - t0
    best.stopped = stop.is_set() and (stop_event is not None and stop_event.is_set())
    if progress:
        progress({"elapsed": best.elapsed, "evaluations": best.evaluations, "length": best.length,
                  "unplaced": len(best.unplaced), "result": best, "final": True})
    return best
