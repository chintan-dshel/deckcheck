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
CHUNK = 20_000


def drain(x) -> None:
    """Empty a large container a chunk at a time. Freeing a 5-million-entry list or dict is one C call that holds
    the GIL for hundreds of milliseconds and stalls the protocol thread (spec §3, measured on a 300 MB mesh)."""
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, (dict, list, set)):
                drain(v)
        while x:
            for _ in range(min(CHUNK, len(x))):
                x.popitem()
    elif isinstance(x, list):
        while x:
            del x[-CHUNK:]
    elif isinstance(x, set):
        while x:
            for _ in range(min(CHUNK, len(x))):
                x.pop()


def drain_source(src: SourceFile) -> None:
    for b in src.blocks:
        drain(b.cards)
    drain(src.blocks)


def drain_index(ix) -> None:
    for name in ("defs", "possible", "dups", "refs", "problems", "unchecked", "uncertain_defs", "uncertain_uses"):
        drain(getattr(ix, name))


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
        self._drops: set[str] = set()
        self._light: dict[str, SourceFile] = {}  # include-only parses, kept across scans until their file changes
        self._dirty = True
        self._lock = threading.Lock()
        self.reading = threading.Lock()  # held while parses are freed; requests never wait for it

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
        """Record that a file's parse is stale; the worker frees it (apply_drops) before the next check."""
        with self._lock:
            self._drops.add(_key(_norm(path)))

    def apply_drops(self) -> None:
        """Worker thread: free the parses of changed files, a chunk at a time."""
        with self.reading:  # the drops are taken under it too: parsed() must not see a stale parse as current
            with self._lock:
                drops, self._drops = self._drops, set()
            for k in drops:
                self._light.pop(k, None)
            for cache in list(self._caches.values()):
                for k in drops:
                    src = cache.pop(k, None)
                    if src is not None:
                        drain_source(src)

    def parsed(self, main: Path, path: Path) -> SourceFile | None:
        """The model's parse of a file, unless the file changed since (a drop not yet applied counts)."""
        k = _key(_norm(path))
        with self._lock:
            if k in self._drops:
                return None
            return self._caches.get(_key(_norm(main)), {}).get(k)

    def open_models(self) -> set[str]:
        open_files = set(self._overlay)
        return {m for m in self._caches if self._reach.get(m, {m}) & open_files}

    def release_closed(self) -> list[str]:
        """Worker thread: free the parse caches of models with no open file (M2 spec §6). Returns their keys."""
        keep = self.open_models()
        released = []
        with self.reading:
            for m in list(self._caches):
                if m not in keep:
                    cache = self._caches.pop(m)
                    for src in cache.values():
                        drain_source(src)
                    drain(cache)
                    released.append(m)
        return released

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
        light = self._light
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

    def model_mb(self, main: Path) -> float:
        """Total size of every file the model reaches, from the include scan (a lone deck: its own size)."""
        k = _key(_norm(main))
        paths = [self._light[f].path for f in self._reach.get(k, ()) if f in self._light] or [_norm(main)]
        total = 0
        for p in paths:
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total / 2**20

    def is_orphan(self, main_key: str) -> bool:
        """A deck checked as its own model that another main deck now includes: its old findings must go."""
        return main_key not in self._mains and any(main_key in r for r in self._reach.values())

    def models_for(self, path: Path) -> list[Path]:
        k = _key(_norm(path))
        found = sorted((p for m, p in self._mains.items() if k in self._reach[m]), key=str)
        return found or [_norm(path)]
