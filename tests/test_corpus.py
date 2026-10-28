import hashlib
import zipfile
from pathlib import Path

import pytest

from bakeoff.corpus import CorpusHashError, CorpusRootError, Entry, fetch, load_manifest


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _zip_with(tmp_path: Path, files: dict[str, bytes]) -> Path:
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return z


def test_fetch_zip_returns_root(tmp_path):
    z = _zip_with(tmp_path, {"model-v1/model/main.key": b"*KEYWORD\n*END\n", "model-v1/model/inc.k": b"*KEYWORD\n"})
    e = Entry("demo", 2, z.as_uri(), _sha(z), "*/model/main.key", "test")
    root = fetch(e, cache=tmp_path / "cache")
    assert root.name == "main.key" and root.read_bytes() == b"*KEYWORD\n*END\n"


def test_fetch_plain_file(tmp_path):
    k = tmp_path / "deck.k"
    k.write_bytes(b"*KEYWORD\n*END\n")
    e = Entry("plain", 1, k.as_uri(), _sha(k), "deck.k", "test")
    assert fetch(e, cache=tmp_path / "cache").read_bytes() == b"*KEYWORD\n*END\n"


def test_fetch_is_cached(tmp_path):
    k = tmp_path / "deck.k"
    k.write_bytes(b"*KEYWORD\n")
    e = Entry("plain", 1, k.as_uri(), _sha(k), "deck.k", "test")
    first = fetch(e, cache=tmp_path / "cache")
    k.unlink()  # source gone: a second fetch must not need it
    assert fetch(e, cache=tmp_path / "cache") == first


def test_hash_mismatch_raises_and_cleans(tmp_path):
    k = tmp_path / "deck.k"
    k.write_bytes(b"*KEYWORD\n")
    e = Entry("bad", 1, k.as_uri(), "0" * 64, "deck.k", "test")
    with pytest.raises(CorpusHashError):
        fetch(e, cache=tmp_path / "cache")
    assert not (tmp_path / "cache" / "bad").exists()


def test_ambiguous_root_raises(tmp_path):
    z = _zip_with(tmp_path, {"a/main.key": b"x", "b/main.key": b"y"})
    e = Entry("amb", 2, z.as_uri(), _sha(z), "*/main.key", "test")
    with pytest.raises(CorpusRootError):
        fetch(e, cache=tmp_path / "cache")


def test_in_place_entry_returns_the_original_path(tmp_path):
    # Local decks (e.g. the LS-DYNA install's examples) are read where they are, so relative includes keep working.
    k = tmp_path / "examples" / "run.key"
    k.parent.mkdir()
    k.write_bytes(b"*KEYWORD\n*INCLUDE\n../shared/control.key\n*END\n")
    e = Entry("local", 1, k.as_uri(), _sha(k), "run.key", "test", in_place=True)
    assert fetch(e, cache=tmp_path / "cache") == k
    assert not (tmp_path / "cache").exists()


def test_in_place_entry_still_checks_the_hash(tmp_path):
    k = tmp_path / "run.key"
    k.write_bytes(b"*KEYWORD\n")
    e = Entry("local", 1, k.as_uri(), "0" * 64, "run.key", "test", in_place=True)
    with pytest.raises(CorpusHashError):
        fetch(e, cache=tmp_path / "cache")


def test_load_manifest(tmp_path):
    m = tmp_path / "manifest.toml"
    m.write_text('[[deck]]\nname = "x"\ntier = 1\nurl = "file:///x"\nsha256 = "ab"\nroot = "x.k"\nterms = "t"\n',
                 encoding="utf-8")
    assert load_manifest(m) == [Entry("x", 1, "file:///x", "ab", "x.k", "t")]
