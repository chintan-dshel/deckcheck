"""Spec §11: pip install works from a clean environment with no runtime dependencies."""
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.install
ROOT = Path(__file__).parent.parent


def test_wheel_installs_clean_and_runs(tmp_path):
    dist = tmp_path / "dist"
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(dist)], check=True,
                   capture_output=True)
    [wheel] = dist.glob("deckcheck-0.1.0-*.whl")
    env_dir = tmp_path / "clean"
    venv.create(env_dir, with_pip=True)
    py = env_dir / "Scripts" / "python.exe"
    subprocess.run([str(py), "-m", "pip", "install", "--no-index", str(wheel)], check=True, capture_output=True)
    listed = subprocess.run([str(py), "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True).stdout
    assert {line.split("==")[0] for line in listed.split()} <= {"deckcheck", "pip", "setuptools"}
    run = subprocess.run([str(env_dir / "Scripts" / "deckcheck.exe"), str(ROOT / "tests/torture/seeded_mistakes/main.k")],
                         capture_output=True, text=True)
    assert run.returncode == 1 and "DC004" in run.stdout and "Traceback" not in run.stderr
    names = zipfile.ZipFile(wheel).namelist()
    for needed in ("deckcheck/data/keywords.json", "deckcheck/data/overrides.toml", "deckcheck/data/definers.toml",
                   "deckcheck/data/dc005_audit.toml", "deckcheck/NOTICE"):
        assert needed in names, needed
    assert any(n.endswith("licenses/LICENSE") or n.endswith("/LICENSE") for n in names)
