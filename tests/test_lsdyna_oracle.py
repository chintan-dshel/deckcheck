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


import subprocess

import bakeoff.lsdyna_oracle as oracle


def test_timeout_is_a_rejection(monkeypatch, tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*END\n")

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(oracle.subprocess, "run", hang)
    ok, log = oracle.lsdyna_reads(tmp_path, timeout_s=1)
    assert ok is False and "timeout" in log
