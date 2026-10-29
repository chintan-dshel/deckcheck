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


from deckcheck.keywords import load, overrides  # noqa: E402

TARGETS = ("field", "fields", "card", "option")


def test_every_override_targets_real_keywords_and_has_evidence():
    data = load()["keywords"]
    for o in overrides()["override"]:
        assert sum(k in o for k in ("keyword", "keywords", "keyword_prefix")) == 1, o
        assert sum(t in o for t in TARGETS) == 1, o
        assert o["evidence"] and o["reason"] and o["set"], o


import re  # noqa: E402

from deckcheck.keywords import override_targets  # noqa: E402


def _names(card):
    return [f["name"] for f in card.get("fields", [])] + [n for c in card.get("cards", []) for n in _names(c)]


def _series(card):
    return ([card["name"]] if card.get("kind") == "series" else []) + [n for c in card.get("cards", []) for n in _series(c)]


def test_override_lint():
    """Every override must be able to fire: its targets exist, and so do the fields, cards and type fields it names."""
    data = load()["keywords"]
    for o in overrides()["override"]:
        targets = override_targets(o)
        assert targets and all(t in data for t in targets), o
        names = {t: [n for c in data[t]["cards"] for n in _names(c)] for t in targets}
        if "field" in o:
            having = [t for t in targets if o["field"] in names[t]]
            assert having, o
            if "keyword" in o or "keywords" in o:
                assert having == targets, o
            if "link_by" in o["set"]:
                assert all(o["set"]["link_by"] in names[t] for t in having), (o, [t for t in having if o["set"]["link_by"] not in names[t]])
        if "fields" in o:
            assert all(f in names[t] for t in targets for f in o["fields"]), o
        if "card" in o:
            assert all(o["card"] in [n for c in data[t]["cards"] for n in _series(c)] for t in targets), o
        if "option" in o:
            assert re.fullmatch(r"(pre|post)/\d+", o["set"]["add_option"]["position"]), o


def test_airbag_cn_override_matches_its_evidence_line():
    hit = resolve("*AIRBAG_SIMPLE_PRESSURE_VOLUME_ID").name
    assert any(hit in override_targets(o) for o in overrides()["override"] if o.get("field") == "cn")


def test_resolve_honours_option_overrides():
    assert resolve("*CONSTRAINED_JOINT_REVOLUTE_ID") == Resolved("CONSTRAINED_JOINT_REVOLUTE", ("ID",), "")
    assert resolve("*ICFD_MAT_TITLE") == Resolved("ICFD_MAT", ("TITLE",), "")
    assert resolve("*LOAD_SEGMENT_SET_NONUNIFORM_ID").options == ("ID",)
    assert resolve("*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED_ID") is None  # no evidence for this family


def test_alias_resolves_to_its_data_key():
    from deckcheck.keywords import Resolved, resolve
    assert resolve("*SET_PART_TITLE") == Resolved("SET_PART_LIST", ("TITLE",), "")
    assert resolve("*SET_PART") == Resolved("SET_PART_LIST", (), "")
    assert resolve("*SET_PART_ADD").name == "SET_PART_ADD"
