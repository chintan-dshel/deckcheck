import json

import pytest

pytest.importorskip("ansys.dyna.core")
pytestmark = pytest.mark.extract

from tools.extract_keyword_data import extract_all  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return extract_all()


def test_source_version_recorded(data):
    assert data["source"] == {"package": "ansys-dyna-core", "version": "0.12.1"}


def test_every_class_extracted(data):
    # 3171 exported names in 0.12.1; distinct classes may be fewer if some are aliases (record the real count).
    assert 3000 <= len(data["keywords"]) <= 3171


def test_keyword_names_are_unique(data):
    classes = [k["class"] for k in data["keywords"].values()]
    assert len(set(classes)) == len(classes)


def test_spc_set_id_option_and_links(data):
    k = data["keywords"]["BOUNDARY_SPC_SET"]
    assert k["options"] == [{"name": "ID", "position": "pre/2", "title_order": 1}]
    assert k["links"] == {"cid": "DEFINE_COORDINATE_SYSTEM", "nsid": "SET_NODE"}
    opt = [c for c in k["cards"] if c["option"] == "ID"][0]
    assert [(f["name"], f["offset"], f["width"]) for f in opt["fields"]] == [("id", 0, 10), ("heading", 10, 70)]
    main = [c for c in k["cards"] if c["option"] is None][0]
    assert {k: v for k, v in main["fields"][0].items() if k != "default"} == {
        "name": "nsid", "type": "int", "offset": 0, "width": 10}


def test_part_is_a_table_group_heading_then_ids(data):
    k = data["keywords"]["PART"]
    assert k["cards"][0]["kind"] == "table_group"
    sub = k["cards"][0]["cards"]
    assert sub[0]["fields"][0]["name"] == "heading" and sub[1]["fields"][0]["name"] == "pid"
    assert k["links"]["mid"] == "MAT"


def test_part_inertia_present_with_links(data):
    k = data["keywords"]["PART_INERTIA"]
    names = [f["name"] for c in k["cards"] for f in c.get("fields", [])]
    assert "pid" in names and k["links"]["mid"] == "MAT"


def test_conditional_cards_are_flagged(data):
    flags = [c["conditional"] for k in data["keywords"].values() for c in k["cards"]]
    assert any(flags) and not all(flags)


def test_extraction_is_deterministic():
    assert json.dumps(extract_all(), sort_keys=True) == json.dumps(extract_all(), sort_keys=True)


def _all_fields(card):
    return [f["name"] for f in card.get("fields", [])] + [n for c in card.get("cards", []) for n in _all_fields(c)]


def test_card_set_keywords_have_their_cards_and_options(data):
    # SECTION_*/HOURGLASS are pydyna CardSets: their cards live inside the set, not on the keyword.
    section = data["keywords"]["SECTION_SOLID"]
    assert "secid" in [n for c in section["cards"] for n in _all_fields(c)]
    assert {"name": "TITLE", "position": "pre/1", "title_order": 1} in section["options"]
    assert "hgid" in [n for c in data["keywords"]["HOURGLASS"]["cards"] for n in _all_fields(c)]
    assert all(c.get("cards") for k in data["keywords"].values() for c in k["cards"] if c["kind"] == "card_set")


def _walk(cards):
    for c in cards:
        yield c
        yield from _walk(c.get("cards", []))


def test_section_shell_conditions_and_lengths(data):
    item = data["keywords"]["SECTION_SHELL"]["cards"][0]
    assert item["kind"] == "card_set" and item["length"] is None
    angle = [c for c in item["cards"] if c.get("name") == "angle"][0]
    assert angle["when"] == "self.icomp == 1"
    assert angle["length"] == "2 if self.nip == 0 else self.nip"
    xi = [c for c in item["cards"] if c["kind"] == "table"][0]
    assert xi["length"] == "self.nipp"
    assert xi["when"] == "self.elform in [101, 102, 103, 104, 105]"


def test_unbounded_tables_have_no_length(data):
    curve = [c for c in data["keywords"]["DEFINE_CURVE"]["cards"] if c["kind"] == "table"][0]
    assert curve["length"] is None and curve["when"] is None


def test_field_defaults(data):
    first = data["keywords"]["SECTION_SHELL"]["cards"][0]["cards"][0]["fields"]
    assert {f["name"]: f["default"] for f in first}["nip"] == 2
    assert {f["name"]: f["default"] for f in first}["icomp"] == 0
    assert {f["name"]: f["default"] for f in first}["secid"] is None


def test_every_card_has_when_and_counts_have_length(data):
    for k in data["keywords"].values():
        for c in _walk(k["cards"]):
            assert "when" in c and c["conditional"] == (c["when"] is not None)
            if c["kind"] in ("table", "series", "card_set", "table_group"):
                assert "length" in c
