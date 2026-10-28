"""Ask LS-DYNA Student about named torture cases; print each verdict and, for rejections, the log tail."""
import sys
from pathlib import Path

from bakeoff.lsdyna_oracle import lsdyna_reads

for name in sys.argv[1:]:
    ok, log = lsdyna_reads(Path("tests/torture") / name)
    print(f"== {name}: {'accepted' if ok else 'rejected'}")
    if not ok:
        print(log)
