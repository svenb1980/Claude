"""Results that are expensive to calculate, kept until the data they depend on changes.

Four rules keep pages responsive:

* The same result is never calculated twice at once. A second request for it waits for
  the calculation that is already running instead of starting another.
* At most one calculation per result runs at a time. When the data changes again while it
  runs, only the newest version is queued behind it. Without this, quick changes in a row
  piled up calculations that all competed for the one core Python computes on.
* Calculations run in their own thread, not in the request. When a visitor gives up and
  clicks again, the work already done isn't lost and isn't repeated.
* After the data changes, a page waits only briefly for the new result. If that isn't
  ready in time, it gets the previous result, marked as stale, and the new one finishes
  in the background.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

log = logging.getLogger(__name__)

# How long a page waits for a new result before showing the previous one.
WAIT_FOR_FRESH = 1.0

_MISSING = object()
_registry: list["ResultCache"] = []


class _Job:
    def __init__(self, version: Hashable, compute: Callable[[], Any]):
        self.version = version
        self.compute = compute
        self.versions: list[Hashable] = [version]  # Every version that waits for this job.
        self.seq = 0
        self.generation = 0
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class ResultCache:
    def __init__(self, name: str, max_entries: int = 64):
        self.name = name
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: OrderedDict[Hashable, tuple[Hashable, int, Any]] = OrderedDict()
        self._jobs: dict[tuple[Hashable, Hashable], _Job] = {}
        self._running: dict[Hashable, _Job] = {}
        self._queued: dict[Hashable, _Job] = {}
        self._seq = itertools.count(1)
        self._generation = 0
        _registry.append(self)

    def get(self, key: Hashable, version: Hashable, compute: Callable[[], Any],
            wait: float | None = None) -> tuple[Any, bool]:
        """Return (value, stale).

        With `wait=None` it always returns a result at least as new as `version`, waiting as
        long as it takes. With a number, it waits at most that long when an older result
        exists. The first result for a key is always waited for, except with `wait=0`, which
        only starts it.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] == version:
                self._entries.move_to_end(key)
                return entry[2], False
            stale = entry[2] if entry is not None else _MISSING
            job = self._jobs.get((key, version))
            if job is None:
                if key not in self._running:
                    job = _Job(version, compute)
                    self._start(key, job)
                elif key in self._queued:
                    # The newest version replaces what was queued. Its waiters get the newer result.
                    job = self._queued[key]
                    job.version, job.compute = version, compute
                    job.versions.append(version)
                else:
                    job = _Job(version, compute)
                    self._queued[key] = job
                self._jobs[(key, version)] = job
        if wait == 0 and stale is _MISSING:
            return None, True  # Only started. Used to run several calculations side by side.
        timeout = None if wait is None or stale is _MISSING else wait
        if job.done.wait(timeout):
            if job.error is not None:
                if stale is not _MISSING and wait is not None:
                    log.warning("Calculation %s failed, showing the previous result: %s", self.name, job.error)
                    return stale, True
                raise job.error
            return job.value, False
        return stale, True

    def _start(self, key, job: _Job) -> None:
        """Called with the lock held."""
        job.seq = next(self._seq)
        job.generation = self._generation
        self._running[key] = job
        threading.Thread(target=self._run, args=(key, job), daemon=True, name=f"calc-{self.name}").start()

    def _run(self, key, job: _Job) -> None:
        try:
            job.value = job.compute()
        except BaseException as exc:  # Handed to whoever waits for it.
            job.error = exc
        with self._lock:
            for version in job.versions:
                if self._jobs.get((key, version)) is job:
                    del self._jobs[(key, version)]
            current = self._entries.get(key)
            # An older calculation that finishes late must not replace a newer result.
            if job.error is None and job.generation == self._generation and (current is None or current[1] < job.seq):
                self._entries[key] = (job.version, job.seq, job.value)
                self._entries.move_to_end(key)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
            del self._running[key]
            following = self._queued.pop(key, None)
            if following is not None:
                self._start(key, following)
        job.done.set()

    def busy(self) -> bool:
        with self._lock:
            return bool(self._running)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            # Running calculations finish but store nothing. New requests start fresh ones.
            self._jobs.clear()
            self._generation += 1


def time_left(deadline: float) -> float:
    """Seconds until a `time.monotonic()` deadline, for pages that wait for several results."""
    return max(0.0, deadline - time.monotonic())


def any_busy() -> bool:
    return any(cache.busy() for cache in _registry)


def clear_all() -> None:
    for cache in _registry:
        cache.clear()
