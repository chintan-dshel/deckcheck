from pathlib import Path

import pytest

from bakeoff.probe import clean_path, measure

TORTURE = Path(__file__).parent / "torture"


def test_clean_path_strips_long_prefix():
    assert clean_path("\\\\?\\C:\\decks\\a.k") == "C:\\decks\\a.k"


def test_clean_path_leaves_plain_paths():
    assert clean_path("C:\\decks\\a.k") == "C:\\decks\\a.k"


def test_seeded_mistakes_findings():
    r = measure(str(TORTURE / "seeded_mistakes" / "main.k"))
    rules = sorted(f["rule"] for f in r["findings"])
    assert rules == ["duplicate_ids", "duplicate_ids", "include_missing", "references_resolve",
                     "unreferenced_entities"]
    assert all(Path(f["file"]).exists() for f in r["findings"] if f["rule"] != "include_missing")


def test_line_ok_is_recorded_per_finding():
    r = measure(str(TORTURE / "seeded_mistakes" / "main.k"))
    missing = next(f for f in r["findings"] if f["rule"] == "include_missing")
    assert missing["line"] == 0 and missing["line_ok"] is False  # known dynars 1.1.0 defect, see spec section 2


@pytest.mark.parametrize("case", ["base", "free_format", "comments", "lowercase", "crlf", "latin1"])
def test_clean_cases_round_trip_and_have_no_errors(case):
    r = measure(str(TORTURE / case / "main.k"))
    assert "error" not in r, r.get("error")
    assert r["round_trip"]["identical"] == r["round_trip"]["files"]
    assert [f for f in r["findings"] if f["severity"] == "Error"] == []


def test_edit_changes_exactly_one_line():
    r = measure(str(TORTURE / "base" / "main.k"))
    assert r["edit"] == {"tried": True, "status": "in_place", "changed_lines": 1}


def test_unparseable_path_reports_error():
    r = measure(str(TORTURE / "does_not_exist.k"))
    assert "error" in r
