import tomllib
from pathlib import Path

TORTURE = Path(__file__).parent / "torture"
CASES = ["base", "free_format", "long_format", "parameter", "include_path", "comments",
         "lowercase", "tabs", "crlf", "latin1", "seeded_mistakes", "blank_title", "part_inertia",
         "crlf_seeded", "latin1_seeded",
         "inc_nested_sibling", "inc_nested_main", "inc_nested_both", "inc_path_precedence", "inc_path_relative",
         "inc_path_backslash", "inc_path_late", "inc_multi", "inc_continuation", "inc_cycle", "inc_transform",
         "end_main", "end_include",
         "table_dangling", "table_before", "table_ids", "contact_type2_bad", "contact_type2_none",
         "contact_type3_bad", "contact_type4_bad", "velocity_styp1_bad", "velocity_styp1_none", "velocity_styp3_bad",
         "inc_path_in_include", "inc_blank_in_continuation", "inc_empty", "long_keyword", "long_section",
         "parameter_ref", "spc_set_id", "spc_set_none", "zero_ref",
         "repeat_velocity", "repeat_mat", "repeat_history_id", "repeat_load_node_set", "nodal_rigid_part",
         "nodal_rigid_none", "set_general_rows",
         "m1d_base", "m1d_bpm_set_none", "m1d_load_node_set_none", "m1d_load_segment_set_none", "m1d_initial_velocity_none",
         "m1d_history_node_set_none", "m1d_dup_part", "m1d_dup_mat", "m1d_dup_section", "m1d_dup_curve", "m1d_dup_node_set",
         "m1d_dup_node", "m1d_dup_node_same", "m1d_overflow_node", "m1d_mixed_free", "m1d_umat", "inc_multi_missing"]


def test_every_case_has_main_and_expected():
    for case in CASES:
        folder = TORTURE / case
        assert (folder / "main.k").is_file(), case
        expected = tomllib.loads((folder / "expected.toml").read_text(encoding="utf-8"))
        assert isinstance(expected["lsdyna_valid"], bool), case
        assert isinstance(expected["findings"], list), case


def test_byte_cases_have_their_bytes():
    assert b"\r\n" in (TORTURE / "crlf" / "main.k").read_bytes()
    assert b"Pr\xfcfplatte" in (TORTURE / "latin1" / "main.k").read_bytes()
    assert b"\r\n" in (TORTURE / "crlf_seeded" / "main.k").read_bytes()
    assert b"\xfc" in (TORTURE / "latin1_seeded" / "main.k").read_bytes()
