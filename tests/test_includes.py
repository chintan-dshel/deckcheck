import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.includes import Problem, resolve_tree

TORTURE = Path(os.path.abspath(Path(__file__).parent / "torture"))
VIVA = Path(__file__).parents[1] / ".corpus" / "vivaplus-50M-seated-v2.0.2"
OFFSETS = ["idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff", "iddoff", "idroff"]


def _expected(case):
    return tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))


RESOLVER_CASES = sorted(p.name for p in TORTURE.iterdir()
                        if (p / "expected.toml").exists() and "resolver" in _expected(p.name))


def _rel(path, root):
    return Path(path).relative_to(root).as_posix()


@pytest.mark.parametrize("case", RESOLVER_CASES)
def test_resolver_follows_lsdyna(case):
    root, exp = TORTURE / case, _expected(case)["resolver"]
    tree = resolve_tree(root / "main.k")
    assert [_rel(f.path, root) for f in tree.files] == exp["files"]
    got = [{"kind": p.kind, "file": _rel(p.file, root), "line": p.line, "name": p.name} for p in tree.problems]
    assert got == exp.get("problems", [])


def test_problem_columns_span_the_name():
    tree = resolve_tree(TORTURE / "seeded_mistakes" / "main.k")
    assert tree.problems[0].columns == (0, len("missing_file.k"))


def test_transform_offsets_by_name():
    node = resolve_tree(TORTURE / "inc_transform" / "main.k").files[1]
    assert node.line == 15
    assert node.offsets == {name: 100 if name in ("idnoff", "ideoff") else 0 for name in OFFSETS}


def test_plain_include_has_no_offsets():
    assert resolve_tree(TORTURE / "include_path" / "main.k").files[1].offsets == {}


@pytest.mark.parametrize("case", RESOLVER_CASES)
def test_tree_paths_are_plain(case):
    for f in resolve_tree(TORTURE / case / "main.k").files:
        s = str(f.path)
        assert f.path.is_absolute() and not s.startswith("\\\\?\\") and s == os.path.normpath(s), s


def test_same_file_twice_is_not_a_cycle(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE\nc.k\n*INCLUDE\nc.k\n*END\n")
    (tmp_path / "c.k").write_text("*KEYWORD\n*END\n")
    tree = resolve_tree(tmp_path / "main.k")
    assert [f.path.name for f in tree.files] == ["main.k", "c.k", "c.k"]
    assert tree.problems == []
    assert tree.files[1].source is tree.files[2].source


def test_relative_main_from_another_cwd(monkeypatch):
    monkeypatch.chdir(TORTURE.parent)
    tree = resolve_tree(Path("torture/include_path/main.k"))
    assert [f.path.name for f in tree.files] == ["main.k", "mat.k"] and tree.problems == []


def test_unfollowed_include_forms_are_reported(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE_BINARY\nx.bin\n*END\n")
    tree = resolve_tree(tmp_path / "main.k")
    assert tree.problems == [Problem("unfollowed", tree.files[0].path, 2, (1, 15), "INCLUDE_BINARY")]


def test_missing_main_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_tree(tmp_path / "nope.k")


@pytest.mark.corpus
@pytest.mark.skipif(not VIVA.exists(), reason="VIVA+ not downloaded")
def test_vivaplus_loads_all_18_files():
    (root,) = VIVA.glob("*/model/50M-seated/vivaplus-50M.key")
    tree = resolve_tree(root)
    assert len(tree.files) == 18
    assert all(str(f.path) == os.path.normpath(str(f.path)) and ".." not in f.path.parts for f in tree.files)
    assert [p for p in tree.problems if p.kind != "unfollowed"] == []


def _transform_deck(tmp_path, keyword_line, offset_cards):
    (tmp_path / "mesh.k").write_text("*KEYWORD\n*END\n")
    (tmp_path / "main.k").write_text(f"*KEYWORD\n{keyword_line}\nmesh.k\n{offset_cards}*END\n")
    return resolve_tree(tmp_path / "main.k")


def test_free_format_offsets_have_all_eight(tmp_path):
    tree = _transform_deck(tmp_path, "*INCLUDE_TRANSFORM", "100,100\n\n")
    assert tree.files[1].offsets == {name: 100 if name in ("idnoff", "ideoff") else 0 for name in OFFSETS}


def test_long_format_transform_offsets_are_unread(tmp_path):
    tree = _transform_deck(tmp_path, "*INCLUDE_TRANSFORM +", f"{'10000000':>20}" * 4 + "\n" + f"{'10000000':>20}" * 3 + "\n")
    assert [(p.kind, p.line, p.name) for p in tree.problems] == [("unread", 2, "INCLUDE_TRANSFORM")]


def test_unread_offset_spans_its_field(tmp_path):
    tree = _transform_deck(tmp_path, "*INCLUDE_TRANSFORM", "     1.0E7       abc\n\n")
    assert [(p.kind, p.line, p.columns, p.name) for p in tree.problems] == [
        ("unread", 4, (5, 10), "1.0E7"), ("unread", 4, (17, 20), "abc")]


def test_dangling_continuation_is_reported_missing(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE\nsub/ +\n*PART\n*END\n")
    tree = resolve_tree(tmp_path / "main.k")
    assert [(p.kind, p.line, p.name) for p in tree.problems] == [("missing", 3, "sub/")]
