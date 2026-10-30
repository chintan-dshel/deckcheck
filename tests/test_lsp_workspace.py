from pathlib import Path

from deckcheck.includes import _key, _norm
from deckcheck.lsp.workspace import Settings, Workspace
from deckcheck.reader import SourceFile

PART = "*KEYWORD\n*PART\np\n         1         1         1\n*END\n"
MAT = "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n"


def _write(folder: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="latin-1")


def _ws(folder, **opts):
    ws = Workspace([folder], Settings.from_options(opts, folder))
    ws.scan()
    return ws


def test_include_opened_alone_belongs_to_its_main(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n", "mat.k": MAT, "part.k": PART})
    assert _ws(tmp_path).models_for(tmp_path / "part.k") == [_norm(tmp_path / "main.k")]


def test_file_in_two_models(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n",
                      "mat.k": MAT})
    assert sorted(_ws(tmp_path).models_for(tmp_path / "mat.k")) == [_norm(tmp_path / "a.k"), _norm(tmp_path / "b.k")]


def test_unincluded_file_is_its_own_main(tmp_path):
    _write(tmp_path, {"solo.k": PART})
    assert _ws(tmp_path).models_for(tmp_path / "solo.k") == [_norm(tmp_path / "solo.k")]


def test_cycle_leaves_each_file_its_own_main(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nb.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\na.k\n*END\n"})
    assert _ws(tmp_path).models_for(tmp_path / "a.k") == [_norm(tmp_path / "a.k")]


def test_include_path_is_followed(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE_PATH\nlib\n*INCLUDE\nmat.k\n*END\n", "lib/mat.k": MAT})
    assert _ws(tmp_path).models_for(tmp_path / "lib" / "mat.k") == [_norm(tmp_path / "main.k")]


def test_main_decks_setting_overrides_detection(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n",
                      "mat.k": MAT})
    ws = _ws(tmp_path, mainDecks=["b.k"])
    assert ws.models_for(tmp_path / "mat.k") == [_norm(tmp_path / "b.k")]


def test_exclude_glob_is_not_scanned(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    ws = _ws(tmp_path, exclude=["main.k"])
    assert ws.models_for(tmp_path / "mat.k") == [_norm(tmp_path / "mat.k")]


def test_overlay_is_the_source_while_open(tmp_path):
    _write(tmp_path, {"mat.k": MAT})
    ws = _ws(tmp_path)
    ws.open(tmp_path / "mat.k", "edited")
    assert ws.source(_norm(tmp_path / "mat.k")) == "edited" and ws.synced(tmp_path / "mat.k")


def test_close_drops_overlay_and_cache(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    ws = _ws(tmp_path)
    main = _norm(tmp_path / "main.k")
    ws.open(tmp_path / "mat.k", "edited")
    ws.cache_for(main)[_key(_norm(tmp_path / "mat.k"))] = SourceFile(Path("x.k"), [], None)
    ws.close(tmp_path / "mat.k")
    assert ws.source(_norm(tmp_path / "mat.k")) is None
    ws.apply_drops()
    assert _key(_norm(tmp_path / "mat.k")) not in ws.cache_for(main)


def test_change_drops_that_file_from_every_cache(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n",
                      "mat.k": MAT})
    ws = _ws(tmp_path)
    k = _key(_norm(tmp_path / "mat.k"))
    for main in ("a.k", "b.k"):
        ws.cache_for(_norm(tmp_path / main))[k] = SourceFile(Path("x.k"), [], None)
    ws.open(tmp_path / "mat.k", MAT)
    ws.change(tmp_path / "mat.k", MAT + "$ edit\n")
    ws.apply_drops()
    assert all(k not in ws.cache_for(_norm(tmp_path / m)) for m in ("a.k", "b.k"))


def test_unreadable_file_does_not_stop_the_scan(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    (tmp_path / "junk.k").write_bytes(bytes(range(256)) * 4096)
    assert _ws(tmp_path).models_for(tmp_path / "mat.k") == [_norm(tmp_path / "main.k")]


def test_drops_wait_for_the_worker(tmp_path):
    """Freeing a big parse holds the GIL; the protocol thread only records the drop, the worker applies it."""
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    ws = _ws(tmp_path)
    k = _key(_norm(tmp_path / "mat.k"))
    ws.cache_for(_norm(tmp_path / "main.k"))[k] = SourceFile(Path("x.k"), [], None)
    ws.drop_file(tmp_path / "mat.k")
    assert k in ws.cache_for(_norm(tmp_path / "main.k"))
    ws.apply_drops()
    assert k not in ws.cache_for(_norm(tmp_path / "main.k"))


def test_drain_empties_containers_and_parses():
    from deckcheck.lsp.workspace import drain, drain_source
    from deckcheck.reader import Block, Card, SourceFile
    d, lst, s = {i: {i: i} for i in range(50_000)}, list(range(50_000)), set(range(50_000))
    for x in (d, lst, s):
        drain(x)
    assert not d and not lst and not s
    src = SourceFile(Path("m.k"), [Block("NODE", 1, None, [Card(i, "") for i in range(50_000)])], None)
    cards = src.blocks[0].cards
    drain_source(src)
    assert not src.blocks and not cards
