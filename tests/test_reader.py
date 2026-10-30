import tomllib
from pathlib import Path

from deckcheck.keywords import Resolved
from deckcheck.reader import Card, read_file

TORTURE = Path(__file__).parent / "torture"


def _read(case):
    return read_file(TORTURE / case / "main.k")


def _shape(source):
    return [(b.name, b.line, [c.line for c in b.cards]) for b in source.blocks]


def test_base_blocks_and_cards():
    src = _read("base")
    assert [b.name for b in src.blocks][:8] == ["KEYWORD", "TITLE", "CONTROL_TERMINATION", "PART", "SECTION_SHELL",
                                                "MAT_ELASTIC", "NODE", "ELEMENT_SHELL"]
    part = src.blocks[3]
    assert part.line == 7
    assert part.cards == [Card(9, "plate"), Card(11, "         1         1         1")]
    assert part.resolved == Resolved("PART", (), "")


def test_blank_title_is_a_card():
    assert _read("blank_title").blocks[3].cards[0] == Card(9, "")


def test_comment_lines_are_not_cards():
    blocks = {b.name: b for b in _read("comments").blocks}
    assert blocks["CONTROL_TERMINATION"].cards == [Card(7, "    1.0E-6")]
    assert blocks["MAT_ELASTIC"].cards == [Card(20, "         1   7.85E-9  210000.0       0.3")]
    assert [c.line for c in blocks["NODE"].cards] == [22, 24, 25, 26]


def test_crlf_reads_like_lf():
    crlf = _read("crlf")
    assert _shape(crlf) == _shape(_read("base"))
    assert not any("\r" in c.text for b in crlf.blocks for c in b.cards)


def test_latin1_title_keeps_its_bytes():
    assert _read("latin1").blocks[3].cards[0] == Card(9, "Pr\xfcfplatte")


def test_latin1_bytes_do_not_break_lines(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes(b"*KEYWORD\n*PART\nA\x85B\x0bC\x0cD\x1cE\n         1\n*END\n")
    assert read_file(deck).blocks[1].cards == [Card(3, "A\x85B\x0bC\x0cD\x1cE"), Card(4, "         1")]


def test_lowercase_and_title_option():
    src = _read("lowercase")
    assert src.blocks[5].name == "MAT_ELASTIC_TITLE"
    assert src.blocks[5].resolved == Resolved("MAT_ELASTIC", ("TITLE",), "")


def test_free_format_is_flagged_per_card():
    part = _read("free_format").blocks[3]
    assert part.cards == [Card(7, "plate"), Card(8, "1,1,1")]
    assert [c.free for c in part.cards] == [False, True]


def test_long_format_suffix():
    mat = _read("long_format").blocks[5]
    assert mat.name == "MAT_ELASTIC" and mat.resolved.format == "+"


def test_tabs_are_kept_raw():
    mat = next(b for b in _read("tabs").blocks if b.name == "MAT_ELASTIC")
    assert "\t" in mat.cards[0].text


def test_file_edges(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes(b"preamble text\n*KEYWORD\n*PART   $ trailing comment\nx")
    src = read_file(deck)
    assert [(b.name, b.line, b.cards) for b in src.blocks] == [("KEYWORD", 2, []), ("PART", 3, [Card(4, "x")])]
    empty = tmp_path / "empty.k"
    empty.write_bytes(b"")
    assert read_file(empty).blocks == [] and read_file(empty).end_line is None


def test_text_after_end_is_read_as_lsdyna_reads_it():
    lsdyna_ignores_it = tomllib.loads((TORTURE / "end_main" / "expected.toml").read_text(encoding="utf-8"))["lsdyna_valid"]
    names = [b.name for b in _read("end_main").blocks]
    assert ("NOT_A_KEYWORD" not in names) == lsdyna_ignores_it


def test_read_from_text_matches_disk():
    path = TORTURE / "base" / "main.k"
    assert read_file(path, text=path.read_bytes().decode("latin-1")) == read_file(path)


def test_read_from_text_uses_the_text_not_the_disk():
    src = read_file(TORTURE / "base" / "main.k", text="*KEYWORD\n*PART\nedited\n         9         1         1\n")
    assert [b.name for b in src.blocks] == ["KEYWORD", "PART"]
    assert src.blocks[1].cards[1] == Card(4, "         9         1         1")


def test_block_keeps_its_keyword_line():
    assert _read("base").blocks[0].text.startswith("*KEYWORD")
