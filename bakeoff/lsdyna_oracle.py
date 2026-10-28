"""Run LS-DYNA Student on a deck folder to decide whether it is valid input."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

LSDYNA_EXE = Path(r"C:\Program Files\LS-DYNA Suite R16.1 Student\lsdyna"
                  r"\ls-dyna_smp_d_R16.1_180-gd50332dbe5_winx64_ifort190_sse2_studentversion.exe")
NORMAL = re.compile(r"N\s*o\s*r\s*m\s*a\s*l\s+t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n")


def lsdyna_reads(case_dir: Path, timeout_s: float = 120) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "case"
        shutil.copytree(case_dir, work)
        env = {**os.environ, "LSTC_LICENSE": "Ansys"}
        try:
            proc = subprocess.run([str(LSDYNA_EXE), "i=main.k", "ncpu=1"], cwd=work, env=env,
                                  capture_output=True, text=True, encoding="latin-1", timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False, f"timeout after {timeout_s} s"
        messag = work / "messag"
        log = messag.read_text(encoding="latin-1") if messag.exists() else proc.stdout
        ok = bool(NORMAL.search(log)) or bool(NORMAL.search(proc.stdout))
        return ok, "\n".join(log.splitlines()[-40:])
