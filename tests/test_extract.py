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
    assert main["fields"][0] == {"name": "nsid", "type": "int", "offset": 0, "width": 10}


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
