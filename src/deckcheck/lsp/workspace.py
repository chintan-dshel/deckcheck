"""What the server knows about the workspace (M2 spec §4.2, §4.4): the editor's unsaved text, which main decks
each file belongs to, and parsed files kept per model between checks. Detection uses the light include walk:
M1b's location rules, reading only *INCLUDE* blocks."""
import fnmatch
import threading
from dataclasses import dataclass, field
from pathlib import Path

from deckcheck.includes import _key, _norm, resolve_tree
from deckcheck.reader import SourceFile, read_includes

DECK_SUFFIXES = (".k", ".key", ".dyn")


@dataclass
class Settings:
    main_decks: list[Path] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    live_threshold: float = 2.0
    memory_mb: int = 2048
    ignore: frozenset[str] = frozenset()

    @classmethod
    def from_options(cls, opts: dict, folder: Path) -> "Settings":
        return cls(main_decks=[_norm(folder / m) for m in opts.get("mainDecks", [])],
                   exclude=list(opts.get("exclude", [])),
                   live_threshold=float(opts.get("liveThresholdSeconds", 2.0)),
                   memory_mb=int(opts.get("memoryMB", 2048)),
                   ignore=frozenset(c.upper() for c in opts.get("ignore", [])))


class Workspace:
    def __init__(self, folders: list[Path], settings: Settings):
        self.folders = [_norm(f) for f in folders]
        self.settings = settings
        self._overlay: dict[str, str] = {}
        self._reach: dict[str, set[str]] = {}   # main key -> keys of every file its include tree reaches
        self._mains: dict[str, Path] = {}
        self._caches: dict[str, dict[str, SourceFile]] = {}
        self._dirty = True
        self._lock = threading.Lock()

    # the editor's text
    def open(self, path: Path, text: str) -> None:
        self.change(path, text)

    def change(self, path: Path, text: str) -> None:
        with self._lock:
            self._overlay[_key(_norm(path))] = text
        self.drop_file(path)

    def close(self, path: Path) -> None:
        with self._lock:
            self._overlay.pop(_key(_norm(path)), None)
        self.drop_file(path)

    def source(self, path: Path) -> str | None:
        return self._overlay.get(_key(_norm(path)))

    def synced(self, path: Path) -> bool:
        return _key(_norm(path)) in self._overlay

    # parsed files
    def cache_for(self, main: Path) -> dict[str, SourceFile]:
        return self._caches.setdefault(_key(_norm(main)), {})

    def drop_file(self, path: Path) -> None:
        k = _key(_norm(path))
        for cache in list(self._caches.values()):
            cache.pop(k, None)

    def open_models(self) -> set[str]:
        open_files = set(self._overlay)
        return {m for m in self._caches if self._reach.get(m, {m}) & open_files}

    def release_closed(self) -> None:
        """Drop the parse caches of models with no open file (M2 spec §6)."""
        keep = self.open_models()
        for m in list(self._caches):
            if m not in keep:
                del self._caches[m]

    # main decks
    def mark_dirty(self) -> None:
        self._dirty = True

    def ensure_scanned(self) -> None:
        if self._dirty:
            self.scan()

    def _excluded(self, path: Path) -> bool:
        for folder in self.folders:
            try:
                rel = path.relative_to(folder).as_posix()
            except ValueError:
                continue
            if any(fnmatch.fnmatch(rel, g) for g in self.settings.exclude):
                return True
        return False

    def _decks(self) -> list[Path]:
        out = []
        for folder in self.folders:
            for p in folder.rglob("*"):
                if p.suffix.lower() in DECK_SUFFIXES and p.is_file() and not self._excluded(p):
                    out.append(_norm(p))
        return sorted(out)

    def scan(self) -> None:
        light: dict[str, SourceFile] = {}
        reach: dict[str, set[str]] = {}
        mains: dict[str, Path] = {}
        candidates = self.settings.main_decks or self._decks()
        for deck in candidates:
            try:
                tree = resolve_tree(deck, source=self.source, cache=light, reader=read_includes)
            except (OSError, ValueError):
                continue
            reach[_key(deck)] = {_key(f.path) for f in tree.files}
            mains[_key(deck)] = deck
        if not self.settings.main_decks:
            included = set().union(*(r - {k} for k, r in reach.items())) if reach else set()
            mains = {k: p for k, p in mains.items() if k not in included}
        with self._lock:
            self._reach = {k: reach[k] for k in mains}
            self._mains = mains
            self._dirty = False

    def models_for(self, path: Path) -> list[Path]:
        k = _key(_norm(path))
        found = sorted((p for m, p in self._mains.items() if k in self._reach[m]), key=str)
        return found or [_norm(path)]
