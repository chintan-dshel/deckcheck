"""For an accepted case, run LS-DYNA and print d3hsp lines that echo any of the given values, so what LS-DYNA read
can be seen: python -m bakeoff.m1d_winner <case> <value> [<value> ...]."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bakeoff.lsdyna_oracle import LSDYNA_EXE

case, values = Path("tests/torture") / sys.argv[1], sys.argv[2:]
with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "case"
    shutil.copytree(case, work)
    subprocess.run([str(LSDYNA_EXE), "i=main.k", "ncpu=1"], cwd=work, env={**os.environ, "LSTC_LICENSE": "Ansys"},
                   capture_output=True, timeout=120)
    text = (work / "d3hsp").read_text(encoding="latin-1") if (work / "d3hsp").exists() else ""
    for n, line in enumerate(text.splitlines(), 1):
        if any(v in line for v in values):
            print(n, line.rstrip())
