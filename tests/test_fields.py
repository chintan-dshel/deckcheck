from deckcheck.conditions import UNKNOWN
from deckcheck.fields import read_fields
from deckcheck.keywords import layout
from deckcheck.reader import read_file


def block(tmp_path, text):
    path = tmp_path / "b.k"
    path.write_bytes(text.encode("latin-1"))
    return read_file(path).blocks[0]


def fields(tmp_path, text, **kw):
    problems = []
    out = list(read_fields(block(tmp_path, text), problems=problems, **kw))
    return out, problems


def values(out, name):
    return [f.value for f in out if f.name == name]


def test_section_shell_card_set_with_conditional_series(tmp_path):
    out, problems = fields(tmp_path, "*SECTION_SHELL\n"
                           "         1         2       1.0         3       0.0         0         1\n"
                           "       1.0       1.0       1.0       1.0\n"
                           "       0.0      45.0      90.0\n"
                           "         2         2\n"
                           "       2.0       2.0       2.0       2.0\n")
    assert values(out, "secid") == [1, 2]
    assert values(out, "angle") == [0.0, 45.0, 90.0]
    assert [f.line for f in out if f.name == "angle"] == [4, 4, 4]
    assert values(out, "t1") == [1.0, 2.0]
    assert problems == []


def test_part_table_group_with_blank_heading(tmp_path):
    out, problems = fields(tmp_path, "*PART\n\n         1         1         1\nsecond\n         2         1         1\n")
    pids = [f for f in out if f.name == "pid"]
    assert [(f.value, f.line, f.start, f.end) for f in pids] == [(1, 3, 9, 10), (2, 5, 9, 10)]
    assert problems == []


def test_id_option_card_comes_first(tmp_path):
    out, _ = fields(tmp_path, "*BOUNDARY_SPC_SET_ID\n         7fixed end\n         3         0         1\n")
    assert values(out, "id") == [7] and values(out, "nsid") == [3]
    assert [f.line for f in out if f.name == "nsid"] == [3]


def test_long_format_suffix(tmp_path):
    line = f"{1:>20}{'7.85E-9':>20}{'210000.0':>20}{0.3:>20}"
    out, _ = fields(tmp_path, "*MAT_ELASTIC +\n" + line + "\n")
    mid = [f for f in out if f.name == "mid"][0]
    assert (mid.value, mid.start, mid.end) == (1, 19, 20)
    assert values(out, "e") == [210000.0]


def test_free_format(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n1,7.85E-9,210000.0,0.3\n")
    mid = [f for f in out if f.name == "mid"][0]
    assert (mid.value, mid.start, mid.end) == (1, 0, 1)
    assert values(out, "pr") == [0.3]


def test_free_card_short(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n1,2\n")
    assert values(out, "mid") == [1] and values(out, "e") == [None]
    assert [f for f in out if f.name == "ro"][0][2:4] == (2, 3)
    assert problems == []


def test_full_width_value(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n1234567890   7.85E-9\n")
    mid = [f for f in out if f.name == "mid"][0]
    assert (mid.value, mid.start, mid.end) == (1234567890, 0, 10)


def test_blank_row_in_table(tmp_path):
    out, problems = fields(tmp_path, "*NODE\n       1             0.0\n\n       2             1.0\n")
    nids = [(f.value, f.line) for f in out if f.name == "nid"]
    assert nids == [(1, 2), (None, 3), (2, 4)]
    assert problems == []


def test_parameter_substitution(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9    &young       0.3\n",
                    params={"YOUNG": 210000.0})
    assert values(out, "e") == [210000.0]
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9     &nope       0.3\n", params={})
    assert values(out, "e") == [UNKNOWN]


def test_undecided_condition_stops_the_block(tmp_path):
    out, problems = fields(tmp_path, "*SECTION_SHELL\n"
                           "         1         2       1.0         3       0.0         0    &undef\n"
                           "       1.0       1.0       1.0       1.0\n"
                           "       0.0      45.0      90.0\n", params={})
    assert values(out, "secid") == [1]
    assert [(p.kind, p.line) for p in problems] == [("unread", 4)]


def test_cards_after_the_layout_start_another_instance(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n"
                                     "         2   7.85E-9  210000.0       0.3\n")
    assert [(f.value, f.line) for f in out if f.name == "mid"] == [(1, 2), (2, 3)] and problems == []


def test_repeated_instance_includes_its_option_card(tmp_path):
    out, _ = fields(tmp_path, "*BOUNDARY_SPC_SET_ID\n         1first\n         3\n         2second\n         4\n")
    assert values(out, "id") == [1, 2] and values(out, "nsid") == [3, 4]


def test_optional_cards_are_read_when_present(tmp_path):
    # pydyna: 'self._cards[1].has_nondefault_values() or ...' (lib/cards.py reads, then keeps a non-default card)
    out, problems = fields(tmp_path, "*CONTROL_SHELL\n      20.0\n       1.0         1\n")
    assert values(out, "intgrd") == [1] and problems == []


def test_flag_card_decided_after_reading_it(tmp_path):
    mpp = "*CONTACT_AUTOMATIC_SINGLE_SURFACE_MPP\n         0\n"
    main = "         5         0         2\n       0.0\n       1.0\n"
    out, problems = fields(tmp_path, mpp + "&                  1\n" + main)
    assert values(out, "ssid") == [5] and values(out, "chksegs") == [1] and problems == []
    out, problems = fields(tmp_path, mpp + main)
    assert values(out, "ssid") == [5] and values(out, "chksegs") == [] and problems == []


def test_legacy_element_solid(tmp_path):
    out, problems = fields(tmp_path, "*ELEMENT_SOLID\n       1       1       1       2       3       4       5       6"
                                     "       7       8\n       2       1       9      10      11      12      13      14"
                                     "      15      16\n")
    assert values(out, "eid") == [1, 2] and values(out, "n8") == [8, 16] and problems == []


def test_two_card_element_solid(tmp_path):
    out, _ = fields(tmp_path, "*ELEMENT_SOLID\n       1       1\n       1       2       3       4       5       6"
                              "       7       8\n")
    assert values(out, "eid") == [1] and values(out, "n1") == [1]


def test_column_condition_per_row(tmp_path):
    thick = f"{2.0:>16}{2.0:>16}{2.0:>16}{2.0:>16}\n"
    out, problems = fields(tmp_path, "*ELEMENT_SHELL_THICKNESS\n       1       1       1       2       3       4\n"
                           + thick + "       2       1       2       5       6       3\n" + thick)
    assert values(out, "eid") == [1, 2] and problems == []


def test_rows_override(tmp_path):
    out, problems = fields(tmp_path, "*SET_SOLID\n         1\n         1         2\n         3\n")
    assert values(out, "sid") == [1] and values(out, "k1") == [1, 3] and problems == []


def test_stop_override(tmp_path):
    out, problems = fields(tmp_path, "*FREQUENCY_DOMAIN_RANDOM_VIBRATION_FATIGUE\n         1\n      0.03\n         1\n"
                                     "\n                   3      2001\n         1        -1\n")
    assert values(out, "pid") == [] and [(p.kind, p.line) for p in problems] == [("unread", 7)]


def test_bad_value(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n       abc   7.85E-9\n")
    assert values(out, "mid") == [UNKNOWN]
    assert [(p.kind, p.line, p.start, p.end) for p in problems] == [("bad", 2, 7, 10)]


def test_integral_float_in_int_field(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n        1.\n")
    assert values(out, "mid") == [1] and problems == []


def test_contact_optional_card_a_is_not_extra(tmp_path):
    _, problems = fields(tmp_path, "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n         1         0         2\n"
                         "       0.0\n       1.0\n         1\n")
    assert problems == []


def test_wanted_filters_fields(tmp_path):
    out, _ = fields(tmp_path, "*PART\nplate\n         1         2         3\n", wanted=frozenset({"mid"}))
    assert [(f.name, f.value) for f in out] == [("mid", 3)]


def test_layout_applies_overrides():
    table = layout("DEFINE_TABLE")["cards"]
    rows = [c for c in table if c["kind"] == "table"][0]
    assert [(f["name"], f["width"], f.get("link")) for f in rows["fields"]] == [
        ("value", 20, None), ("lcid", 10, None)]
    surfa = [f for c in layout("CONTACT_AUTOMATIC_GENERAL")["cards"] for f in c.get("fields", []) if f["name"] == "surfa"][0]
    assert surfa["link_by"] == "surfatyp" and surfa["link_map"]["2"] == "SET_PART"
    assert layout("PART")["cards"][0]["cards"][1]["fields"][2]["link"] == "MAT"
    assert "ID" in {o["name"] for o in layout("CONSTRAINED_JOINT_REVOLUTE")["options"]}


def test_thickness_beta_card_5_to_8_only_for_8_node_shells(tmp_path):
    thick = f"{0.7:>16}{0.7:>16}{0.7:>16}{0.7:>16}{30.0:>16}\n"
    out, problems = fields(tmp_path, "*ELEMENT_SHELL_THICKNESS_BETA\n       1       1       1       2       3       4\n"
                           + thick + "       2       1       2       5       6       3\n" + thick)
    assert values(out, "eid") == [1, 2] and values(out, "n1") == [1, 2] and problems == []


def test_condition_on_own_and_earlier_fields(tmp_path):
    # CONTROL_IMPLICIT_EIGENVALUE card 2: 'self.eigmth in [...] or (self.isolid != 0 or ...)', isolid on that card
    out, problems = fields(tmp_path, "*CONTROL_IMPLICIT_EIGENVALUE\n        10\n         1\n")
    assert problems == [] and values(out, "neig") == [10] and values(out, "isolid") == [1]


def test_blank_field_span_is_empty_at_its_column(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9    \n")
    e = [f for f in out if f.name == "e"][0]
    assert (e.value, e.start, e.end) == (None, 20, 20)


def test_partial_repeated_instance_is_reported(tmp_path):
    # final review I4: a repeated instance that runs out of cards may mean a layout that is too short
    _, problems = fields(tmp_path, "*BOUNDARY_SPC_SET_ID\n         1first\n         3\n         2second\n")
    assert [(p.kind, p.line) for p in problems] == [("unread", 4)]
