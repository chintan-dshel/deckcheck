"""Download external test decks pinned by sha256 into a local cache. They are never committed."""
import hashlib
import shutil
import tomllib
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

CACHE = Path(".corpus")


class CorpusHashError(Exception):
    pass


class CorpusRootError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    tier: int
    url: str
    sha256: str
    root: str
    terms: str
    in_place: bool = False  # a local file:// deck read where it is, so relative includes keep resolving


def load_manifest(path: Path) -> list[Entry]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [Entry(**d) for d in data.get("deck", [])]


def _root(entry: Entry, dest: Path) -> Path:
    matches = sorted(dest.glob(entry.root))
    if len(matches) != 1:
        raise CorpusRootError(f"{entry.name}: root {entry.root!r} matched {len(matches)} files")
    return matches[0]


def fetch(entry: Entry, cache: Path = CACHE) -> Path:
    if entry.in_place:
        path = Path(urllib.request.url2pathname(urllib.parse.urlparse(entry.url).path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.sha256:
            raise CorpusHashError(f"{entry.name}: expected {entry.sha256}, got {digest}")
        return path
    dest = cache / entry.name
    if dest.exists():
        return _root(entry, dest)
    dest.mkdir(parents=True)
    blob = dest / ".download"
    digest = hashlib.sha256()
    with urllib.request.urlopen(entry.url) as r, open(blob, "wb") as f:
        while chunk := r.read(1 << 20):
            digest.update(chunk)
            f.write(chunk)
    if digest.hexdigest() != entry.sha256:
        shutil.rmtree(dest)
        raise CorpusHashError(f"{entry.name}: expected {entry.sha256}, got {digest.hexdigest()}")
    if zipfile.is_zipfile(blob):
        with zipfile.ZipFile(blob) as z:
            z.extractall(dest)
        blob.unlink()
    else:
        blob.rename(dest / Path(entry.root).name)
    return _root(entry, dest)
