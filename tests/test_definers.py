from deckcheck.definers import definers, family_kind, not_definer
from deckcheck.keywords import layout, walk_cards


def test_every_row_reaches_a_keyword_with_its_field():
    import tomllib
    from importlib import resources
    from deckcheck.keywords import override_targets
    rows = tomllib.loads(resources.files("deckcheck.data").joinpath("definers.toml").read_text(encoding="utf-8"))
    for row in rows["definer"]:
        assert any(row["field"] in {f["name"] for c in walk_cards(layout(k)["cards"]) for f in c.get("fields", [])}
                   for k in override_targets(row)), row["kind"]


def test_core_definers():
    d = definers()
    assert ("PART", "pid") in d["PART"] and ("PART", "pid") in d["PART_INERTIA"]
    assert ("MAT", "mid") in d["MAT_ELASTIC"]
    assert "MAT_ADD_EROSION" not in d
    assert ("SECTION", "secid") in d["SECTION_SHELL"]
    assert ("ICFD_PART", "pid") in d["ICFD_PART"]  # from overrides.toml set.defines


def test_family_kind():
    assert family_kind("SET_PART_TITLE") == "SET_PART"
    assert family_kind("PART_MOVE") == "PART"
    assert family_kind("PARTITION") is None
    assert family_kind("DEFINE_COORDINATE_NODES") == "DEFINE_COORDINATE_SYSTEM"
    assert family_kind("CONTROL_TERMINATION") is None


def test_not_definer():
    assert not_definer("MAT_ADD_EROSION") and not not_definer("MAT_ELASTIC")
