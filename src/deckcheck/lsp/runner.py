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


class Runner:
    def __init__(self, models: Callable[[Path], list[Path]], check: Callable, publish: Callable,
                 threshold: float, clock: Callable[[], float] = time.monotonic, debounce: float = 0.3,
                 prepare: Callable[[], None] = lambda: None,
                 report_error: Callable[[BaseException], None] = lambda e: None):
        self.models, self.check, self.publish, self.prepare = models, check, publish, prepare
        self.report_error = report_error
        self._typed_unknown: dict[str, float] = {}  # typed while the model's speed was unknown (its first check)
        self.threshold, self.clock, self.debounce = threshold, clock, debounce
        self.durations: dict[str, float] = {}
        self.active: str | None = None
        self._incoming: list[tuple[Path, str, float]] = []
        self._pending: dict[str, _Job] = {}
        self._gen: dict[str, int] = {}
        self._order = itertools.count()
        self._cv = threading.Condition()

    @staticmethod
    def key(path: Path) -> str:
        return _key(_norm(path))

    def live(self, main: Path) -> bool:
        took = self.durations.get(self.key(main))
        return took is not None and took < self.threshold

    def request(self, file: Path, reason: str) -> None:
        with self._cv:
            self._incoming.append((file, reason, self.clock()))
            self._cv.notify()

    def _schedule(self, main: Path, reason: str, at: float) -> None:
        if reason == "close":  # wakes the worker for prepare() (freeing closed models) without starting a check
            return
        k = self.key(main)
        if reason == "change" and not self.live(main):
            if k not in self.durations:  # first check still running: decide once its speed is known
                self._typed_unknown[k] = at
            return
        self._gen[k] = self._gen.get(k, 0) + 1
        due = at + (self.debounce if reason == "change" else 0.0)
        self._pending[k] = _Job(main, due, next(self._order))

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
        start = self.clock()
        try:
            report, error = self.check(job.main), None
        except Exception as e:  # a whole-check failure: published as such (spec §6), never raised into the loop
            report, error = None, e
        took = self.clock() - start
        self._drain()
        with self._cv:
            if error is None:
                self.durations[k] = took
            typed = self._typed_unknown.pop(k, None)
            if typed is not None and self.live(job.main):  # a small model: the typing supersedes this result
                self._schedule(job.main, "change", typed)
            stale = self._gen[k] != gen
        if not stale:
            self.publish(job.main, report, error)
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
