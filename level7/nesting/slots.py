"""How many nesting runs may work at the same time in this application, and how many processor cores each gets.

Every run can use the whole processor (LEVEL7's search processes + sparrow). Several runs at once without a
limit overloaded the machine and froze the windows, so runs take a slot; the processor cores (one is kept for
the windows) are divided between the slots. A run that finds no free slot waits for one.
"""
from __future__ import annotations

import os
import threading


def cores() -> int:
    return os.cpu_count() or 2


def auto_limit() -> int:
    """Default: one run per 4 cores (at least one)."""
    return max(1, (cores() - 1) // 4)


class NestSlots:
    def __init__(self, limit: int = 1):
        self._cv = threading.Condition()
        self.active = 0
        self.limit = max(1, int(limit))

    def set_limit(self, n: int):
        with self._cv:
            self.limit = max(1, int(n))
            self._cv.notify_all()

    def acquire(self, timeout: float | None = None) -> bool:
        with self._cv:
            if not self._cv.wait_for(lambda: self.active < self.limit, timeout):
                return False
            self.active += 1
            return True

    def release(self):
        with self._cv:
            self.active = max(0, self.active - 1)
            self._cv.notify_all()

    def workers(self) -> int:
        """Processor cores for one run: the cores (minus one for the windows) divided between the slots."""
        return max(1, (cores() - 1) // self.limit)


NEST_SLOTS = NestSlots(1)
