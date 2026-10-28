from deckcheck import keywords


def test_shipped_data_loads():
    data = keywords.load()
    assert data["source"]["version"] == "0.12.1"
    assert {"PART", "PART_INERTIA", "BOUNDARY_SPC_SET"} <= set(data["keywords"])


def test_load_is_cached():
    assert keywords.load() is keywords.load()
