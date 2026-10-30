import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.rules import CODES, check

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))
IMPLEMENTED = ["DC000", "DC001", "DC002", "DC004", "DC006"]  # Task 4 adds DC003, Task 5 DC005


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
