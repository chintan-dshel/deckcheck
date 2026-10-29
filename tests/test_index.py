import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.includes import resolve_tree
from deckcheck.index import OFFSET_FIELD, build, pack, unpack
from deckcheck.keywords import layout, walk_cards

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))


def i10(*vals):
    return "".join(f"{v:>10}" for v in vals)


BASE = ("*PART\nplate\n" + i10(1, 1, 1) + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
        "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n")


def index(tmp_path, body, files=None):
    (tmp_path / "main.k").write_bytes(("*KEYWORD\n" + body + "*END\n").encode("latin-1"))
    for rel, text in (files or {}).items():
        (tmp_path / rel).write_bytes(text.encode("latin-1"))
    return build(resolve_tree(tmp_path / "main.k"))


def dangling(ix, root):
    return [{"kind": r.kind, "id": r.id, "file": r.path.relative_to(root).as_posix(), "line": r.line,
             "columns": [r.start, r.end]} for r in ix.dangling()]


def duplicates(ix, root):
    return [{"kind": d.kind, "id": d.id, "file": d.path.relative_to(root).as_posix(), "line": d.line,
             "columns": [d.start, d.end]} for d in ix.duplicates()]


@pytest.mark.parametrize("case", CASES)
def test_torture_index(case):
    expected = tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))
    table = expected.get("index", {})
    root = Path(os.path.abspath(TORTURE / case))  # the resolver's paths are abspath+normpath, never resolve()
    ix = build(resolve_tree(TORTURE / case / "main.k"))
    assert dangling(ix, root) == table.get("dangling", [])
    assert duplicates(ix, root) == table.get("duplicates", [])


def test_seeded_unused_material():
    ix = build(resolve_tree(TORTURE / "seeded_mistakes" / "main.k"))
    assert 7 not in ix.used("MAT") and 99 in ix.used("MAT")


def test_zero_and_blank_are_no_reference(tmp_path):
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, 1, 0, 0, 0, 0, 0)))
    assert ix.dangling() == [] and ix.used("HOURGLASS") == set()


def test_negative_plain_link_is_a_possible_use_not_a_reference(tmp_path):
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, -5)))
    assert ix.dangling() == [] and 5 in ix.used("MAT")


def card_text(key, **values):
    """A fixed-format card holding `values`, laid out by the first card of `key` that has all their fields."""
    for card in walk_cards(layout(key)["cards"]):
        spec = {f["name"]: f for f in card.get("fields", [])}
        if values.keys() <= spec.keys():
            line = [" "] * 80
            for name, v in values.items():
                f = spec[name]
                line[f["offset"]:f["offset"] + f["width"]] = str(v).rjust(f["width"])
            return "".join(line).rstrip()
    raise KeyError(values)


def test_negative_cn_is_a_curve_reference(tmp_path):
    body = ("*AIRBAG_SIMPLE_PRESSURE_VOLUME\n" + card_text("AIRBAG_SIMPLE_PRESSURE_VOLUME", sid=1) + "\n"
            + card_text("AIRBAG_SIMPLE_PRESSURE_VOLUME", cn=-1) + "\n")
    ix = index(tmp_path, body)
    assert ("DEFINE_CURVE", 1) in {(r.kind, r.id) for r in ix.dangling()}


def test_link_by_type_value(tmp_path):
    contact = "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(5, 0, "{t}", 0) + "\n" + i10(0.0) + "\n" + i10(1.0) + "\n"
    assert [(r.kind, r.id) for r in index(tmp_path, BASE + contact.format(t=2)).dangling()] == [("SET_PART", 5)]
    assert index(tmp_path, BASE + contact.format(t=0)).dangling() == []  # type 0 is unmapped: unchecked


def test_unresolved_family_member_makes_kind_uncertain(tmp_path):
    contact = "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(5, 0, 2, 0) + "\n" + i10(0.0) + "\n" + i10(1.0) + "\n"
    ix = index(tmp_path, BASE + contact + "*SET_PART_TITLE\nnamed set\n" + i10(5) + "\n" + i10(1) + "\n")
    assert ix.dangling() == [] and "SET_PART" in ix.uncertain_defs and not ix.checked("SET_PART")


def test_unread_block_makes_its_kinds_uncertain(tmp_path):
    body = BASE.replace(i10(1, 1, 1), i10(1, 99, 1)).replace(
        "*SECTION_SHELL\n" + i10(1, 2), "*SECTION_SHELL\n" + i10(1, 2, 1.0, 3, 0.0, 0, "&undef")).replace(
        i10(1.0, 1.0, 1.0, 1.0) + "\n", i10(1.0, 1.0, 1.0, 1.0) + "\n" + i10(0.0, 45.0, 90.0) + "\n")  # left unread
    ix = index(tmp_path, body)
    assert ix.dangling() == [] and "SECTION" in ix.uncertain_defs
    assert any(p.kind == "unread" for _, p in ix.problems)


def test_parameter_in_id_field(tmp_path):
    ix = index(tmp_path, "*PARAMETER\nI mm               1\n" + BASE.replace(i10(1, 1, 1), i10(1, 1, "&mm")))
    assert ix.dangling() == [] and 1 in ix.used("MAT")
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, "&nope")))
    assert ix.dangling() == [] and "MAT" in ix.uncertain_uses


def transform(offsets: dict) -> str:
    order = ["idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff", "iddoff"]
    return ("*INCLUDE_TRANSFORM\nsub.k\n" + i10(*(offsets.get(f, 0) for f in order)) + "\n"
            + i10(offsets.get("idroff", 0)) + "\n\n\n")


@pytest.mark.skipif("MAT" not in OFFSET_FIELD, reason="LS-DYNA did not decide the material offset")
def test_transform_offset_shifts_definitions(tmp_path):
    sub = "*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"
    body = transform({OFFSET_FIELD["MAT"]: 100}) + BASE.replace(i10(1, 1, 1), i10(1, 1, 101)).split("*MAT_ELASTIC")[0]
    ix = index(tmp_path, body, {"sub.k": sub})
    assert ix.dangling() == [] and 101 in ix.defs["MAT"]


@pytest.mark.skipif("MAT" not in OFFSET_FIELD, reason="LS-DYNA did not decide the material offset")
def test_same_file_two_transforms(tmp_path):
    sub = "*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"
    f = OFFSET_FIELD["MAT"]
    ix = index(tmp_path, transform({f: 100}) + transform({f: 200}) + BASE, {"sub.k": sub})
    assert ix.duplicates() == [] and {1, 101, 201} <= set(ix.defs["MAT"])


def test_unrefereed_offset_makes_kind_uncertain(tmp_path):
    sub = "*KEYWORD\n*DEFINE_BOX\n" + i10(1, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0) + "\n*END\n"
    ix = index(tmp_path, transform({f: 7 for f in ("idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff",
                                                   "iddoff", "idroff")}) + BASE, {"sub.k": sub})
    if "DEFINE_BOX" not in OFFSET_FIELD:
        assert "DEFINE_BOX" in ix.uncertain_defs


def test_unfollowed_include_blinds_the_index(tmp_path):
    ix = index(tmp_path, "*INCLUDE_AUTO_OFFSET\nother.k\n" + BASE.replace(i10(1, 1, 1), i10(1, 1, 99)))
    assert ix.blind and ix.dangling() == []


def test_missing_include_does_not_blind(tmp_path):
    ix = index(tmp_path, "*INCLUDE\nnot_there.k\n" + BASE.replace(i10(1, 1, 1), i10(1, 1, 99)))
    assert [(r.kind, r.id) for r in ix.dangling()] == [("MAT", 99)]


def test_pack_roundtrip():
    for loc in [(0, 1, 0, 0), (3, 2**20 + 5, 1500, 1600), (65535, 2**31 - 1, 65535, 65535)]:
        assert unpack(pack(*loc)) == loc
