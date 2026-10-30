from pathlib import Path

from deckcheck.coverage import DC005_KINDS, dc005_silent, not_checked
from deckcheck.includes import resolve_tree
from deckcheck.index import build

TORTURE = Path(__file__).parent / "torture"


def run(case):
    tree = resolve_tree(TORTURE / case / "main.k")
    return tree, build(tree)


def whats(items):
    return [n.what for n in items]


def test_clean_deck_lists_only_the_dc005_scope_line():
    tree, ix = run("base")
    assert whats(not_checked(tree, ix)) == ["unused definitions of other kinds (DC005)"]


def test_unfollowed_include_blinds_all_references(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE_AUTO_OFFSET\nx.k\n*END\n", encoding="latin-1")
    tree = resolve_tree(tmp_path / "main.k")
    items = not_checked(tree, build(tree))
    assert items[0].what == "all references (DC001, DC006)" and items[0].count == 1
    assert set(dc005_silent(tree, build(tree))) == set(DC005_KINDS)


def test_unknown_parameter_makes_mat_uses_uncertain(tmp_path):
    body = ("*PART\nplate\n" + f"{1:>10}{1:>10}{'&nope':>10}" + "\n*SECTION_SHELL\n" + f"{1:>10}{2:>10}" + "\n"
            + f"{1.0:>10}" * 4 + "\n*MAT_ELASTIC\n" + f"{1:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n")
    (tmp_path / "main.k").write_text("*KEYWORD\n" + body + "*END\n", encoding="latin-1")
    tree = resolve_tree(tmp_path / "main.k")
    silent = dc005_silent(tree, build(tree))
    assert "MAT" in silent and silent["MAT"].startswith("main.k:")
    assert "unused MAT (DC005)" in whats(not_checked(tree, build(tree)))


def test_unknown_keyword_silences_dc005(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*NOT_A_REAL_KEYWORD\n1\n*END\n", encoding="latin-1")
    tree = resolve_tree(tmp_path / "main.k")
    assert "NOT_A_REAL_KEYWORD" in dc005_silent(tree, build(tree))["MAT"]
    assert "keywords deckcheck doesn't know (passed through)" in whats(not_checked(tree, build(tree)))
