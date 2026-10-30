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
    ix = index(tmp_path, BASE + contact + "*SET_PART_SPECIAL\nnamed set\n" + i10(5) + "\n" + i10(1) + "\n")
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


# --- Final review findings (M1c): each reproduces the reviewer's deck


def i20(*vals):
    return "".join(f"{v:>20}" for v in vals)


def raw(tmp_path, text, files=None):
    (tmp_path / "main.k").write_bytes(text.encode("latin-1"))
    for rel, body in (files or {}).items():
        (tmp_path / rel).write_bytes(body.encode("latin-1"))
    return build(resolve_tree(tmp_path / "main.k"))


def test_long_deck_two_card_solid_is_not_read_as_legacy(tmp_path):
    rows = "".join(i20(e, 1) + "\n" + i20(*range(1, 9)) + "\n" for e in (1, 2))
    ix = raw(tmp_path, "*KEYWORD LONG=Y\n*ELEMENT_SOLID\n" + rows + "*END\n")
    assert ix.duplicates() == []


def test_free_two_card_solid_is_not_read_as_legacy(tmp_path):
    rows = "10000001,12345678\n1,2,3,4,5,6,7,8\n10000002,12345678\n1,2,3,4,5,6,7,8\n"
    ix = raw(tmp_path, "*KEYWORD\n*ELEMENT_SOLID\n" + rows + "*END\n")
    assert ix.duplicates() == []


def test_long_deck_transform_offsets_are_not_read_10_wide(tmp_path):
    sub = "*KEYWORD\n*MAT_ELASTIC\n" + i20(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"
    main = ("*KEYWORD LONG=Y\n*INCLUDE_TRANSFORM\nsub.k\n" + i20(0, 0, 0, 100, 0, 0, 0) + "\n" + i20(0) + "\n\n\n"
            + "*PART\nplate\n" + i20(1, 1, 101) + "\n*SECTION_SHELL\n" + i20(1, 2) + "\n" + i20(1.0, 1.0, 1.0, 1.0)
            + "\n*END\n")
    ix = raw(tmp_path, main, {"sub.k": sub})
    assert ix.dangling() == []


def test_parameter_of_another_type_is_unknown_not_dropped(tmp_path):
    mat = i10(1, "7.85E-9", "210000.0", 0.3)
    for param in (f"{'C mid':<10}{'1':>10}", f"{'R mid':<10}{'1.5':>10}"):
        ix = index(tmp_path, "*PARAMETER\n" + param + "\n" + BASE.replace(mat, i10("&mid", "7.85E-9", "210000.0", 0.3)))
        assert ix.dangling() == [] and "MAT" in ix.uncertain_defs, param


def test_huge_values_do_not_crash(tmp_path):
    index(tmp_path, BASE + "*LOAD_NODE_POINT\n99999999999999999999,1,0,1.0\n")
    index(tmp_path, "*AIRBAG_SIMPLE_PRESSURE_VOLUME\n" + card_text("AIRBAG_SIMPLE_PRESSURE_VOLUME", sid=1) + "\n"
          + card_text("AIRBAG_SIMPLE_PRESSURE_VOLUME", cn="-1.0e30") + "\n")
    shell = "*SECTION_SHELL\n" + i10(1, 2, 1.0, "&nip", 0.0, 0, 1) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n" + i10(0.0) + "\n"
    for value in ("1e400", "nan"):
        index(tmp_path, f"*PARAMETER\n{'R nip':<10}{value:>10}\n" + shell)


def test_lenient_python_numbers_are_bad_values(tmp_path):
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, "1_0")))
    assert ix.dangling() == [] and any(p.kind == "bad" for _, p in ix.problems)


def test_unmapped_type_value_makes_its_kinds_uses_uncertain(tmp_path):
    contact = "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(5, 0, 0, 0) + "\n" + i10(0.0) + "\n" + i10(1.0) + "\n"
    ix = index(tmp_path, BASE + contact)
    assert "SET_PART" in ix.uncertain_uses and "PART" in ix.uncertain_uses


def test_curves_after_a_table_make_curve_uses_uncertain(tmp_path):
    table = "*DEFINE_TABLE\n" + i10(10) + "\n" + f"{0.0:>20}{5:>10}\n"
    curve = "*DEFINE_CURVE\n" + i10(5) + "\n" + f"{0.0:>20}{1.0:>20}\n"
    ix = index(tmp_path, BASE + table + curve)
    assert "DEFINE_CURVE" in ix.uncertain_uses


def test_include_transform_makes_transformation_uses_uncertain(tmp_path):
    ix = index(tmp_path, transform({}) + BASE, {"sub.k": "*KEYWORD\n*END\n"})
    assert "DEFINE_TRANSFORMATION" in ix.uncertain_uses


def test_part_set_fallback_under_different_offsets_is_not_checked(tmp_path):
    sub = ("*KEYWORD\n*PART\nplate\n" + i10(1, 1, 1) + "\n*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(1, 0, 2, 0) + "\n"
           + i10(0.0) + "\n" + i10(1.0) + "\n*END\n")
    ix = index(tmp_path, transform({"idpoff": 100, "idsoff": 200}) + BASE, {"sub.k": sub})
    assert ix.dangling() == []


def test_pack_clamps_columns_past_16_bits():
    assert unpack(pack(0, 1, 70004, 70010)) == (0, 1, 65535, 65535)


def test_unchecked_reference_to_missing_set_is_ignored_not_dangling():
    ix = build(resolve_tree(TORTURE / "spc_set_none" / "main.k"))
    assert ix.dangling() == []
    [r] = ix.ignored()
    assert (r.kind, r.id, r.path.name, r.line, r.start, r.end, r.field) == (
        "SET_NODE", 99, "main.k", 22, 8, 10, "BOUNDARY_SPC_SET.nsid")


def test_unchecked_reference_to_defined_set_is_not_ignored():
    ix = build(resolve_tree(TORTURE / "spc_set_id" / "main.k"))
    assert ix.ignored() == []


def test_block_failure_is_recorded_and_run_continues(tmp_path, monkeypatch):
    import deckcheck.index as index_mod
    real = index_mod.read_fields

    def flaky(block, *args, **kwargs):
        if block.name == "MAT_ELASTIC":
            raise RuntimeError("boom")
        return real(block, *args, **kwargs)

    monkeypatch.setattr(index_mod, "read_fields", flaky)
    ix = index(tmp_path, BASE + "*PART\nother\n" + i10(2, 1, 99) + "\n")
    [(fi, line, text)] = ix.failures
    assert (fi, text) == (0, "*MAT_ELASTIC: RuntimeError: boom")
    assert "MAT" in ix.uncertain_defs           # its definitions can't be seen: DC001 stays silent on MAT
    assert 1 in ix.defs.get("SECTION", {})     # the rest of the deck was still read


def test_uncertain_reasons_name_the_file(tmp_path):
    ix = index(tmp_path, BASE + "*PART\nother\n" + i10(2, 1, "&nope") + "\n")
    assert any(r.startswith("main.k:") for r in ix.uncertain_uses["MAT"])
