"""One check at a time across the workspace (M2 spec §6). A model whose last full check took under the threshold
is re-checked a moment after typing pauses; a bigger one only on open, save and outside changes. A request that
arrives while its model is being checked makes that result stale: it is discarded, never published."""
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from deckcheck.includes import _key, _norm


@dataclass
class _Job:
    main: Path
    due: float
    order: int
    reason: str


class Runner:
    def __init__(self, models: Callable[[Path], list[Path]], check: Callable, publish: Callable,
                 threshold: float, clock: Callable[[], float] = time.monotonic, debounce: float = 0.3,
                 prepare: Callable[[], None] = lambda: None,
                 report_error: Callable[[BaseException], None] = lambda e: None,
                 big: Callable[[Path], bool] = lambda m: False, on_demand: Callable[[Path], None] = lambda m: None,
                 on_busy: Callable[[Path], None] = lambda m: None,
                 on_start: Callable[[Path, float | None], None] = lambda m, est: None,
                 on_edit: Callable[[Path], None] = lambda m: None):
        self.models, self.check, self.publish, self.prepare = models, check, publish, prepare
        self.report_error = report_error
        self.big_by_size, self.on_demand = big, on_demand
        self.on_busy, self.on_start, self.on_edit = on_busy, on_start, on_edit
        self._typed_unknown: dict[str, float] = {}  # typed while the model's speed was unknown (its first check)
        self.threshold, self.clock, self.debounce = threshold, clock, debounce
        self.durations: dict[str, float] = {}
        self.active: str | None = None
        self._incoming: list[tuple[Path, str, float]] = []
        self._pending: dict[str, _Job] = {}
        self._gen: dict[str, int] = {}
        self._order = itertools.count()
        self._running: str | None = None
        self._changed = False  # the running model's files changed since its check began
        self._cv = threading.Condition()

    @staticmethod
    def key(path: Path) -> str:
        return _key(_norm(path))

    def live(self, main: Path) -> bool:
        took = self.durations.get(self.key(main))
        return took is not None and took < self.threshold

    def big(self, main: Path) -> bool:
        """Checked on demand and on save only (Chintan, 2026-10-30): a full-vehicle check made opening another
        huge file ~33 % slower for the minute it ran. Measured duration decides; before any check, the size."""
        took = self.durations.get(self.key(main))
        return took >= self.threshold if took is not None else self.big_by_size(main)

    def request(self, file: Path, reason: str) -> None:
        with self._cv:
            self._incoming.append((file, reason, self.clock()))
            self._cv.notify()

    def _schedule(self, main: Path, reason: str, at: float) -> None:
        if reason == "close":  # wakes the worker for prepare() (freeing closed models) without starting a check
            return
        k = self.key(main)
        if k == self._running:
            if reason == "check" and not self._changed:  # asked again while it runs: the running check answers it
                self.on_busy(main)
                return
            if reason in ("change", "save", "external"):
                self._changed = True
        if reason in ("open", "external") and self.big(main):
            if reason == "external":  # the files changed: a check running now reads older text (spec §6)
                self._gen[k] = self._gen.get(k, 0) + 1
            self.on_demand(main)
            return
        if reason == "change" and not self.live(main):
            if k not in self.durations:  # first check still running: decide once its speed is known
                self._typed_unknown[k] = at
            else:  # a big model: the edit is checked when saved, and the engineer is told so
                self.on_edit(main)
            return
        self._gen[k] = self._gen.get(k, 0) + 1
        due = at + (self.debounce if reason == "change" else 0.0)
        self._pending[k] = _Job(main, due, next(self._order), reason)

    def _next(self) -> _Job | None:
        now = self.clock()
        due = [(k, j) for k, j in self._pending.items() if j.due <= now]
        if not due:
            return None
        k, job = min(due, key=lambda kj: (kj[0] != self.active, kj[1].order))
        del self._pending[k]
        return job

    def _drain(self) -> None:
        """Map waiting file requests to their models and queue them. Called before choosing a job and again after
        a check, so a request that arrived during the check makes its result stale."""
        with self._cv:
            incoming, self._incoming = self._incoming, []
        if not incoming:
            return
        self.prepare()
        mapped = [(main, reason, at) for file, reason, at in incoming for main in self.models(file)]
        with self._cv:
            for main, reason, at in mapped:
                self._schedule(main, reason, at)

    def step(self) -> bool:
        try:
            return self._step()
        except Exception as e:  # outside check() (the scan, a model lookup): reported, and the worker lives on
            self.report_error(e)
            return True

    def _step(self) -> bool:
        self._drain()
        with self._cv:
            job = self._next()
            if job is None:
                return False
            k = self.key(job.main)
            gen = self._gen[k]
            self._running, self._changed = k, False
        if self.big(job.main):  # a check long enough to need showing: the estimate is the last measured time
            self.on_start(job.main, self.durations.get(k))
        start = self.clock()
        try:
            report, error = self.check(job.main), None
        except Exception as e:  # a whole-check failure: published as such (spec §6), never raised into the loop
            report, error = None, e
        took = self.clock() - start
        self._drain()
        with self._cv:
            self._running = None
            if error is None:
                self.durations[k] = took
            typed = self._typed_unknown.pop(k, None)
            if typed is not None and self.live(job.main):  # a small model: the typing supersedes this result
                self._schedule(job.main, "change", typed)
            stale = self._gen[k] != gen
        if not stale:
            self.publish(job.main, report, error, job.reason)
        return True

    def _wait(self) -> None:
        with self._cv:
            while not self._incoming:
                now = self.clock()
                if any(j.due <= now for j in self._pending.values()):
                    return
                timeout = min((j.due - now for j in self._pending.values()), default=None)
                self._cv.wait(timeout)

    def _loop(self) -> None:
        while True:
            self._wait()
            self.step()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="deckcheck-runner", daemon=True).start()
