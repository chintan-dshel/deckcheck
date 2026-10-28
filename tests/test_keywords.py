from deckcheck import keywords


def test_shipped_data_loads():
    data = keywords.load()
    assert data["source"]["version"] == "0.12.1"
    assert {"PART", "PART_INERTIA", "BOUNDARY_SPC_SET"} <= set(data["keywords"])


def test_load_is_cached():
    assert keywords.load() is keywords.load()


from deckcheck.keywords import Resolved, resolve  # noqa: E402


def test_resolve_plain():
    assert resolve("*PART") == Resolved("PART", (), "")


def test_resolve_option_suffix():
    assert resolve("*BOUNDARY_SPC_SET_ID") == Resolved("BOUNDARY_SPC_SET", ("ID",), "")


def test_resolve_longest_key_wins():
    assert resolve("*PART_INERTIA").name == "PART_INERTIA"


def test_resolve_title_option():
    r = resolve("*DEFINE_TABLE_TITLE")
    assert r.name == "DEFINE_TABLE" and r.options == ("TITLE",)


def test_resolve_strips_format_suffix():
    assert resolve("*MAT_ELASTIC +") == Resolved("MAT_ELASTIC", (), "+")
    assert resolve("*mat_elastic   ") == Resolved("MAT_ELASTIC", (), "")


def test_resolve_ignores_trailing_comment():
    assert resolve("*PART $ bumper parts").name == "PART"


def test_resolve_unknown_is_none():
    assert resolve("*NOT_A_KEYWORD_AT_ALL") is None


def test_resolve_rejects_non_option_remainder():
    # MAT_ELASTIC exists; "_BANANA" is not one of its options, so this is not MAT_ELASTIC.
    assert resolve("*MAT_ELASTIC_BANANA") is None
