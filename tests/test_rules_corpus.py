import tomllib
from pathlib import Path

import pytest

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST
from deckcheck.rules import check

pytestmark = pytest.mark.corpus
EXPECTED = {d["name"]: d for d in tomllib.loads(
    (Path(__file__).parent / "corpus" / "expected_diagnostics.toml").read_text(encoding="utf-8"))["deck"]}
SMALL = [e for e in load_manifest(MANIFEST) if e.tier == 1]
JUDGED_HERE = ("DC003", "DC004", "DC005", "DC006")


@pytest.mark.parametrize("entry", SMALL, ids=lambda e: e.name)
def test_tier1_diagnostics_match_judged_findings(entry):
    diags = check(fetch(entry)).diagnostics
    got = [(d.code, d.path.name, d.line) for d in diags if d.code in JUDGED_HERE]
    want = [(f["code"], f["file"], f["line"]) for f in EXPECTED.get(entry.name, {}).get("findings", [])]
    assert got == want
    assert not [d for d in diags if d.code == "DC000"]
