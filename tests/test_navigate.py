import os
from pathlib import Path

from deckcheck.conditions import UNKNOWN
from deckcheck.fields import Field
from deckcheck.includes import resolve_tree
from deckcheck.index import Target, build, target


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
