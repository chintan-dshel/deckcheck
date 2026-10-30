import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.rules import CODES, check

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))
IMPLEMENTED = ["DC000", "DC001", "DC002", "DC003", "DC004", "DC005", "DC006"]
EXPECTED_SEEDED_DC005 = []  # a missing include could hold the only reference to MAT 7


def expected(case: str, code: str) -> list[dict]:
    """DC001, DC002 and DC004 follow from the [index] and [resolver] tables (already refereed); the other codes are
    listed one by one in [[diagnostics]]."""
    e = tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))
    if code == "DC001":
        return [{"file": d["file"], "line": d["line"], "columns": d["columns"]} for d in e.get("index", {}).get("dangling", [])]
    if code == "DC002":
        return [{"file": d["file"], "line": d["line"], "columns": d["columns"]} for d in e.get("index", {}).get("duplicates", [])]
    if code == "DC004":
        return [{"file": p["file"], "line": p["line"]} for p in e.get("resolver", {}).get("problems", [])
                if p["kind"] in ("missing", "cycle")]
    return [{"file": d["file"], "line": d["line"], "columns": d["columns"], "severity": d["severity"]}
            for d in e.get("diagnostics", []) if d["code"] == code]


def got(case: str, code: str) -> list[dict]:
    root = Path(os.path.abspath(TORTURE / case))
    out = []
    for d in check(TORTURE / case / "main.k").diagnostics:
        if d.code != code:
            continue
        row = {"file": d.path.relative_to(root).as_posix(), "line": d.line}
        if code != "DC004":
            row["columns"] = [d.start, d.end]
        if code not in ("DC001", "DC002", "DC004"):
            row["severity"] = d.severity
        out.append(row)
    return out


@pytest.mark.parametrize("code", IMPLEMENTED)
@pytest.mark.parametrize("case", CASES)
def test_torture_diagnostics(case, code):
    assert got(case, code) == expected(case, code)


def test_codes():
    assert CODES == ("DC000", "DC001", "DC002", "DC003", "DC004", "DC005", "DC006")


def test_seeded_mistakes_messages():
    ds = {d.code: d for d in check(TORTURE / "seeded_mistakes" / "main.k").diagnostics}
    assert ds["DC004"].message == "include file 'missing_file.k' not found"
    assert ds["DC001"].message == ("*PART mid refers to MAT 99, which is not defined; "
                                   "it may be defined in missing include 'missing_file.k'")
    assert ds["DC001"].severity == "error"
    assert ds["DC002"].message.startswith("PART 1 is defined twice (first at main.k:8)")
    assert ds["DC002"].related[0].line == 8
    assert ds["DC002"].severity == "error"  # m1d_dup_part: LS-DYNA rejects a repeated part id (Error 10176)


def test_dc006_message():
    [d] = [d for d in check(TORTURE / "spc_set_none" / "main.k").diagnostics if d.code == "DC006"]
    assert d.severity == "warning"
    assert d.message == ("*BOUNDARY_SPC_SET nsid refers to SET_NODE 99, which is not defined; "
                         "LS-DYNA accepts this, but the reference has no effect")


def test_dc000_reports_block_failure(tmp_path, monkeypatch):
    import deckcheck.index as index_mod
    real = index_mod.read_fields
    monkeypatch.setattr(index_mod, "read_fields", lambda block, *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
                        if block.name == "MAT_ELASTIC" else real(block, *a, **k))
    (tmp_path / "main.k").write_bytes((TORTURE / "base" / "main.k").read_bytes())
    [d] = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC000"]
    assert d.severity == "warning" and "*MAT_ELASTIC: RuntimeError: boom" in d.message


def dc002(case):
    [d] = [d for d in check(TORTURE / case / "main.k").diagnostics if d.code == "DC002"]
    return d


def test_dc002_node_at_other_coordinates_is_an_error():
    d = dc002("m1d_dup_node")  # Error 11168
    assert d.severity == "error" and d.message == "NODE 1 is defined twice (first at main.k:15) at different coordinates"


def test_dc002_node_at_same_coordinates_is_accepted():
    d = dc002("m1d_dup_node_same")  # accepted, no warning
    assert d.severity == "warning"
    assert d.message == ("NODE 1 is defined twice (first at main.k:15) at the same coordinates; "
                         "LS-DYNA accepts this")


def test_dc002_untested_kind_says_so(tmp_path):
    text = (TORTURE / "m1d_base" / "main.k").read_text(encoding="latin-1").replace(
        "*END", "*HOURGLASS\n" + f"{5:>10}{1:>10}" + "\n*HOURGLASS\n" + f"{5:>10}{1:>10}" + "\n*END")
    (tmp_path / "main.k").write_text(text, encoding="latin-1")
    d = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC002"][0]
    assert d.severity == "warning" and d.message.endswith("; not tested whether LS-DYNA rejects this")


def test_dc003_tab_is_one_warning_per_card():
    ds = [d for d in check(TORTURE / "tabs" / "main.k").diagnostics if d.code == "DC003"]
    assert [(d.line, d.start, d.end) for d in ds] == [(19, 1, 2)]
    assert ds[0].message == "tab in card: LS-DYNA misreads tab-separated cards (use spaces or commas)"


def test_dc003_bad_value(tmp_path):
    body = ("*KEYWORD\n*PART\nplate\n" + f"{1:>10}{1:>10}{'1x':>10}" + "\n*SECTION_SHELL\n" + f"{1:>10}{2:>10}"
            + "\n" + f"{1.0:>10}" * 4 + "\n*MAT_ELASTIC\n" + f"{1:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*END\n")
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    [d] = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC003"]
    assert (d.line, d.start, d.end, d.severity) == (4, 28, 30, "warning")
    assert d.message == "mid: '1x' is not int; LS-DYNA may misread this card"


def test_dc005_unused_material_in_seeded_mistakes_is_silent_because_of_missing_include():
    ds = [d for d in check(TORTURE / "seeded_mistakes" / "main.k").diagnostics if d.code == "DC005"]
    assert [(d.line, d.start, d.end) for d in ds] == EXPECTED_SEEDED_DC005


def test_dc005_message(tmp_path):
    body = ((TORTURE / "base" / "main.k").read_text(encoding="latin-1").replace(
        "*END", "*MAT_ELASTIC\n" + f"{7:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*END"))
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    [d] = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC005"]
    assert d.severity == "warning" and d.message == "MAT 7 is defined but nothing refers to it"


def test_dc005_silent_on_unknown_keyword(tmp_path):
    body = ((TORTURE / "base" / "main.k").read_text(encoding="latin-1").replace(
        "*END", "*MAT_ELASTIC\n" + f"{7:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*NOT_A_REAL_KEYWORD\n7\n*END"))
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    assert [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC005"] == []


def test_dc005_silent_when_an_include_is_missing(tmp_path):
    body = ((TORTURE / "base" / "main.k").read_text(encoding="latin-1").replace(
        "*END", "*INCLUDE\nnowhere.k\n*MAT_ELASTIC\n" + f"{7:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*END"))
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    assert [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC005"] == []


def test_umat_part_material_is_not_reported():
    ds = check(TORTURE / "m1d_umat" / "main.k").diagnostics
    assert not [d for d in ds if d.code in ("DC001", "DC005") and "MAT 2" in d.message]


# --- final review fixes (M1d)

BASE_DECK = (TORTURE / "m1d_base" / "main.k").read_text(encoding="latin-1")


def deck(tmp_path, extra="", files=None, head="*KEYWORD"):
    (tmp_path / "main.k").write_text(BASE_DECK.replace("*KEYWORD", head, 1).replace("*END", extra + "*END"),
                                     encoding="latin-1")
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text, encoding="latin-1")
    return check(tmp_path / "main.k").diagnostics


def test_dc002_node_plus_duplicate_is_not_compared(tmp_path):
    # review C1: a 20-wide *NODE + card read at 8/16 columns compared as different: a false error
    ds = [d for d in deck(tmp_path, "*NODE +\n" + "".join(f"{v:>20}" for v in (1, 0.0, 0.0, 0.0)) + "\n")
          if d.code == "DC002"]
    assert [(d.severity, "could not compare" in d.message) for d in ds] == [("warning", True)]


def test_dc002_node_under_transform_is_not_compared(tmp_path):
    # review I2: a translation moves the nodes; deckcheck doesn't apply it, so it can't say "same coordinates"
    nodes = "*KEYWORD\n*NODE\n       1             0.0             0.0             0.0\n*END\n"
    ds = [d for d in deck(tmp_path, "*INCLUDE_TRANSFORM\nnodes.k\n         0\n\n\n\n", {"nodes.k": nodes})
          if d.code == "DC002"]
    assert [(d.severity, "could not compare" in d.message) for d in ds] == [("warning", True)]


def test_dc002_node_duplicates_scale(tmp_path):
    # review I5: each duplicate searched the whole tree; a mesh included twice must stay fast
    import time
    mesh = "*KEYWORD\n*NODE\n" + "".join(f"{i:>8}{float(i):>16}{0.0:>16}{0.0:>16}\n" for i in range(100, 20100)) + "*END\n"
    start = time.monotonic()
    ds = [d for d in deck(tmp_path, "*INCLUDE\nmesh.k\n*INCLUDE\nmesh.k\n", {"mesh.k": mesh}) if d.code == "DC002"]
    assert len(ds) == 20000 and time.monotonic() - start < 5


def test_keyword_id_is_structural(tmp_path):
    # review I1: *KEYWORD_ID with its job-id card is the deck header, not an unknown keyword
    (tmp_path / "main.k").write_text(BASE_DECK.replace("*KEYWORD", "*KEYWORD_ID\nmyjob", 1), encoding="latin-1")
    report = check(tmp_path / "main.k")
    assert not [n for n in report.not_checked if "doesn't know" in n.what or n.what.startswith("unused MAT")]


def test_keyword_id_long_reads_long_format(tmp_path):
    long_deck = (TORTURE / "m1d_keyword_id_long" / "main.k")
    assert [d.code for d in check(long_deck).diagnostics] == []


def test_tab_in_text_or_unknown_block_is_no_finding(tmp_path):
    # review I3: *TITLE and *COMMENT are text; an unknown keyword passes through untouched (spec §4)
    text = BASE_DECK.replace("deckcheck torture: base model for M1d cases", "review\tdeck").replace(
        "*END", "*COMMENT\nnote\twith tab\n*NOT_A_REAL_KEYWORD\n1\t2\n*END")
    (tmp_path / "main.k").write_text(text, encoding="latin-1")
    assert [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC003"] == []


def test_declared_python_floor_has_tomllib():
    # review I4: the runtime imports tomllib (3.11+); requires-python must not promise 3.10
    root = Path(__file__).parent.parent
    meta = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["requires-python"] == ">=3.11"
    assert "Python 3.11 or newer" in (root / "README.md").read_text(encoding="utf-8")
