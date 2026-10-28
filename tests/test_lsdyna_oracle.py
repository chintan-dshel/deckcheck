import tomllib
from pathlib import Path

import pytest

from bakeoff.lsdyna_oracle import LSDYNA_EXE, lsdyna_reads

TORTURE = Path(__file__).parent / "torture"
needs_lsdyna = pytest.mark.skipif(not LSDYNA_EXE.exists(), reason="LS-DYNA Student not installed")


@pytest.mark.lsdyna
@needs_lsdyna
@pytest.mark.parametrize("case", sorted(p.name for p in TORTURE.iterdir() if (p / "expected.toml").exists()))
def test_torture_deck_matches_lsdyna(case):
    expected = tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))
    ok, log = lsdyna_reads(TORTURE / case)
    assert ok == expected["lsdyna_valid"], f"{case}: LS-DYNA says {ok}\n{log}"
