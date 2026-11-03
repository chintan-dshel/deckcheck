import os
from array import array
from pathlib import Path

from deckcheck.conditions import UNKNOWN
from deckcheck.fields import Field
from deckcheck.includes import resolve_tree
from deckcheck.index import Target, build, target
from deckcheck.navigate import (MAX_HINTS, MAX_OUTLINE, READ_LIMIT, Table, hints, outline, ruler, block_at, explain, explain_keyword, fields_between, hit,
                                 subject)
from deckcheck.reader import read_file

TORTURE = Path(__file__).parent / "torture"


def i10(*vals):
    return "".join(f"{v:>10}" for v in vals)


def i8(*vals):
    return "".join(f"{v:>8}" for v in vals)


NODES = "".join(i8(n) + f"{0.0:>16}" * 3 + "\n" for n in (1, 2, 3, 4))
# main.k lines: 1 *KEYWORD, 2 *INCLUDE, 3 mat.k, 4 *PART, 5 plate, 6 part card, 7 *SECTION_SHELL, 8-9 its cards,
# 10 *NODE, 11-14 nodes, 15 *ELEMENT_SHELL, 16 element, 17 *END. mat.k: 1 *KEYWORD, 2 *MAT_ELASTIC, 3 its card.
MAIN = ("*KEYWORD\n*INCLUDE\nmat.k\n*PART\nplate\n" + i10(1, 1, 1) + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n"
        + i10(1.0, 1.0, 1.0, 1.0) + "\n*NODE\n" + NODES + "*ELEMENT_SHELL\n" + i8(1, 1, 1, 2, 3, 4) + "\n*END\n")
MAT = "*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"


def model(tmp_path, main=MAIN, files=None):
    (tmp_path / "main.k").write_bytes(main.encode("latin-1"))
    for rel, text in ({"mat.k": MAT} if files is None else files).items():
        (tmp_path / rel).write_bytes(text.encode("latin-1"))
    return Path(os.path.abspath(tmp_path / "main.k"))


def nav_of(main):
    from deckcheck.navigate import build_nav
    return build_nav(build(resolve_tree(main)))


def fld(name, value, **spec):
    return Field(name, 1, 0, 1, value, 1, {"name": name, **spec})


def test_target_plain_link():
    assert target(fld("mid", 7, link="MAT"), {}, {}) == Target("MAT", 7, "checked")


def test_target_blank_zero_and_no_link():
    assert target(fld("mid", None, link="MAT"), {}, {}).how == "none"
    assert target(fld("mid", 0, link="MAT"), {}, {}).how == "none"
    assert target(fld("ro", 1.0), {}, {}).how == "none"


def test_target_shifted_by_the_files_offset():
    assert target(fld("mid", 7, link="MAT"), {}, {"idmoff": 1000}) == Target("MAT", 1007, "checked")


def test_target_offset_not_refereed():
    assert target(fld("lcid", 7, link="DEFINE_TRANSFORMATION"), {}, {"idnoff": 5}).how == "offset"
    assert target(fld("mid", 7, link="MAT"), {}, None).how == "offset"


def test_target_unknown_and_not_an_id():
    assert target(fld("mid", UNKNOWN, link="MAT"), {}, {}).how == "unknown"
    assert target(fld("mid", "abc", link="MAT"), {}, {}).how == "not an id"


def test_target_link_by_mapped_and_unmapped():
    spec = {"link_by": "styp", "link_map": {"1": "SET_SEGMENT", "3": "PART"}}
    styp = Field("styp", 1, 10, 11, 3, 1, {"name": "styp"})
    assert target(fld("ssid", 5, **spec), {"styp": styp}, {}) == Target("PART", 5, "checked")
    odd = styp._replace(value=9)
    assert target(fld("ssid", 5, **spec), {"styp": odd}, {}).how == "unmapped"


def test_target_unchecked_negative_and_unknown_sign():
    assert target(fld("nsid", 9, link="SET_NODE", link_when="unchecked"), {}, {}) == Target("SET_NODE", 9, "unchecked")
    assert target(fld("lc", -4, link="DEFINE_CURVE", link_when="negative"), {}, {}) == Target("DEFINE_CURVE", 4, "checked")
    assert target(fld("lc", 4, link="DEFINE_CURVE", link_when="negative"), {}, {}).how == "none"
    assert target(fld("mid", -4, link="MAT"), {}, {}) == Target("MAT", 4, "possible")


def test_target_fallback_kind_under_another_offset():
    # SET_PART falls back to PART; under idsoff without idpoff the two shift differently: a use, never checked
    assert target(fld("psid", 5, link="SET_PART"), {}, {"idsoff": 10}) == Target("SET_PART", 15, "possible")


PARAM = "*KEYWORD\n*PARAMETER\n" + f"{'I m':<10}{1:>10}" + "\n"   # adds two lines: the part card moves to line 8


def test_build_keeps_params_and_long_deck(tmp_path):
    ix = build(resolve_tree(model(tmp_path, MAIN.replace("*KEYWORD\n", PARAM, 1))))
    assert ix.params == {"M": 1} and ix.long_deck is False


def test_find_ignores_matches_across_two_ids():
    # 1 << 56 then 0: the bytes of id 1 appear at offset 7, inside the first two ids
    t = Table(bytearray(array("q", [1 << 56, 0, 1]).tobytes()), array("H", [0, 0, 0]), array("q", [0, 0, 0]))
    assert list(t.find(1)) == [2]


def test_definitions_and_uses_across_includes(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    mat = main.parent / "mat.k"
    assert [(l.path, l.line, l.start, l.end) for l in nav.definitions("MAT", 1)] == [(mat, 3, 9, 10)]
    assert [(l.path, l.line, l.start, l.end) for l in nav.uses("MAT", 1)] == [(main, 6, 29, 30)]
    assert [(l.line, l.start) for l in nav.uses("NODE", 3)] == [(16, 39)]
    assert nav.definitions("MAT", 2) == [] and nav.checked("MAT")


def test_a_duplicate_has_every_definition(tmp_path):
    main = model(tmp_path, files={"mat.k": MAT.replace("*END\n", "*MAT_ELASTIC\n" + i10(1, 1.0, 1.0, 0.3) + "\n*END\n")})
    assert [l.line for l in nav_of(main).definitions("MAT", 1)] == [3, 5]


def test_a_part_set_id_without_a_set_resolves_to_the_part(tmp_path):
    nav = nav_of(model(tmp_path))
    assert [l.line for l in nav.definitions("SET_PART", 1)] == [6]


def test_transform_definition_and_uses():
    case = Path(os.path.abspath(TORTURE / "inc_transform"))
    nav = nav_of(case / "main.k")
    mesh = case / "mesh.k"
    assert [(l.path, l.line, l.start) for l in nav.definitions("NODE", 101)] == [(mesh, 3, 7)]
    assert [(l.path, l.line, l.start) for l in nav.uses("NODE", 101)] == [(mesh, 8, 23)]
    assert nav.definitions("NODE", 1) == []


def test_uses_complete_names_what_it_could_not_place(tmp_path):
    nav = nav_of(model(tmp_path, MAIN.replace(i10(1, 1, 1), i10(1, 1, -1))))  # a negative mid: a possible use
    assert nav.uses_complete("MAT") != [] and nav.uses_complete("SECTION") == []


def at(nav, path, line, col):
    fi = nav.file_index(path)
    block = block_at(nav.tree.files[fi].source, line)
    fields = fields_between(block, line, line, nav.params, nav.long_deck)
    return fi, fields, hit(fields, col)


def test_the_field_under_a_column(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    _, fields, f = at(nav, main, 6, 29)
    assert [x.name for x in fields][:3] == ["pid", "secid", "mid"] and f.name == "mid"
    assert at(nav, main, 16, 23)[2].name == "n1"


def test_padding_and_blank_fields(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    assert at(nav, main, 6, 25)[2] is None            # spaces before mid's value
    assert at(nav, main, 6, 35)[2].name == "eosid"    # blank: hit across its whole 10-wide slot


def test_a_row_deep_in_a_big_table_is_read_alone(tmp_path):
    nodes = "".join(i8(n) + f"{0.0:>16}" * 3 + "\n" for n in range(1, 50_001))
    main = model(tmp_path, "*KEYWORD\n*NODE\n" + nodes + "*END\n", files={})
    nav = nav_of(main)
    block = block_at(nav.tree.files[0].source, 40_002)
    fields = fields_between(block, 40_002, 40_002, nav.params, nav.long_deck)
    assert fields[0].name == "nid" and fields[0].value == 40_000 and fields[0].line == 40_002


def test_deep_in_a_non_uniform_block_says_nothing(tmp_path):
    rows = "".join(i10(n) + "\n" for n in range(1, READ_LIMIT + 1000))
    main = model(tmp_path, "*KEYWORD\n*SET_NODE_LIST\n" + i10(1) + "\n" + rows + "*END\n", files={})
    nav = nav_of(main)
    block = block_at(nav.tree.files[0].source, 5)
    assert fields_between(block, 5, 5, nav.params, nav.long_deck) is not None
    assert fields_between(block, READ_LIMIT + 500, READ_LIMIT + 500, nav.params, nav.long_deck) is None


def test_subject_of_a_reference_and_a_definition(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    fi, fields, f = at(nav, main, 6, 29)
    assert subject(nav, fi, fields, f) == ("MAT", 1, False)
    fi, fields, f = at(nav, main, 6, 9)
    assert subject(nav, fi, fields, f) == ("PART", 1, True)


def test_hover_on_a_resolved_reference(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    text = explain(nav, *at(nav, main, 6, 29))
    assert "**mid**" in text and "columns 21-30" in text and "integer" in text
    assert "mid → MAT 1, *MAT_ELASTIC at mat.k:3" in text


def test_hover_on_a_definition_counts_its_uses(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    text = explain(nav, *at(nav, main.parent / "mat.k", 3, 9))
    assert "Defines MAT 1" in text and "1 use" in text


def test_hover_on_a_dangling_and_an_ignored_reference(tmp_path):
    main = model(tmp_path, MAIN.replace(i10(1, 1, 1), i10(1, 1, 99)))
    nav = nav_of(main)
    assert "MAT 99 is not defined" in explain(nav, *at(nav, main, 6, 29))
    case = Path(os.path.abspath(TORTURE / "spc_set_none"))
    nav = nav_of(case / "main.k")
    assert "LS-DYNA accepts this, but the reference has no effect" in explain(nav, *at(nav, case / "main.k", 22, 9))


def test_hover_on_a_blank_field_gives_its_default(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    assert "blank" in explain(nav, *at(nav, main, 6, 35)) and "default: 0" in explain(nav, *at(nav, main, 6, 35))


def test_hover_value_as_read_after_a_parameter(tmp_path):
    main = model(tmp_path, MAIN.replace("*KEYWORD\n", PARAM, 1).replace(i10(1, 1, 1), i10(1, 1, "&m")))
    nav = nav_of(main)
    text = explain(nav, *at(nav, main, 8, 28))         # "&m" right-aligned in mid's slot: columns 28-29
    assert "&m = 1" in text and "MAT 1" in text


def test_hover_in_a_transformed_file():
    case = Path(os.path.abspath(TORTURE / "inc_transform"))
    nav = nav_of(case / "main.k")
    text = explain(nav, *at(nav, case / "mesh.k", 8, 23))
    assert "NODE 101" in text and "offset 100" in text and "mesh.k:3" in text


def test_hover_on_a_keyword_line(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    assert explain_keyword(block_at(nav.tree.files[0].source, 4)).startswith("*PART")
    src = read_file(tmp_path / "x.k", "*KEYWORD\n*NOT_A_KEYWORD\n1\n")
    assert "not in deckcheck's keyword data; passed through" in explain_keyword(block_at(src, 2))


def test_outline_names_keyword_id_and_title(tmp_path):
    mat = MAT.replace("*MAT_ELASTIC\n", "*MAT_ELASTIC_TITLE\nsteel\n")
    main = model(tmp_path, files={"mat.k": mat})
    nav = nav_of(main)
    names = [e.name for e in outline(nav.tree.files[0].source, nav.params, nav.long_deck)]
    assert names[:6] == ["*KEYWORD", "*INCLUDE", "*PART 1 plate", "*SECTION_SHELL 1", "*NODE", "*ELEMENT_SHELL 1"]
    assert [e.name for e in outline(nav.tree.files[1].source, {}, False)][1:] == ["*MAT_ELASTIC_TITLE 1 steel"]


def test_outline_of_a_block_defining_many_says_how_many_cards(tmp_path):
    nav = nav_of(model(tmp_path))
    node = outline(nav.tree.files[0].source, nav.params, nav.long_deck)[4]
    assert node.name == "*NODE" and node.detail == "4 cards" and (node.line, node.end_line) == (10, 14)


def test_outline_over_the_cap_returns_the_count(tmp_path):
    body = "*KEYWORD\n" + ("*DEFINE_CURVE\n" + i10(1) + "\n") * (MAX_OUTLINE + 1) + "*END\n"
    src = read_file(tmp_path / "big.k", body)
    assert outline(src, {}, False) == MAX_OUTLINE + 2      # *KEYWORD is a block too; *END ends the reading
    at_cap = "*KEYWORD\n" + ("*DEFINE_CURVE\n" + i10(1) + "\n") * (MAX_OUTLINE - 1) + "*END\n"
    assert len(outline(read_file(tmp_path / "ok.k", at_cap), {}, False)) == MAX_OUTLINE


def test_hints_name_each_field_in_the_range(tmp_path):
    nav = nav_of(model(tmp_path))
    got = hints(nav.tree.files[0].source, 6, 6, nav.params, nav.long_deck)
    assert got[:3] == [(6, 9, "pid"), (6, 19, "secid"), (6, 29, "mid")]


def test_hints_are_capped(tmp_path):
    nodes = "".join(i8(n) + f"{0.0:>16}" * 3 + "\n" for n in range(1, 2001))
    nav = nav_of(model(tmp_path, "*KEYWORD\n*NODE\n" + nodes + "*END\n", files={}))
    assert len(hints(nav.tree.files[0].source, 1, 3000, nav.params, nav.long_deck)) == MAX_HINTS


def test_ruler_of_a_part_card(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    block = block_at(nav.tree.files[0].source, 6)
    assert ruler(fields_between(block, 6, 6, {}, False)) == (
        "$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid")


def test_ruler_names_are_cut_to_leave_a_space():
    f = Field("averylongname", 1, 0, 0, None, 1, {"name": "averylongname", "offset": 0, "width": 8})
    g = Field("anotherlongname", 1, 8, 8, None, 1, {"name": "anotherlongname", "offset": 8, "width": 8})
    assert ruler([f, g]) == "$# avery another"
