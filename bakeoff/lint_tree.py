"""Run deckcheck's checks on one deck and write a summary JSON: python -m bakeoff.lint_tree <deck> <out>."""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from deckcheck.rules import check

deck, out = Path(sys.argv[1]), Path(sys.argv[2])
start = time.monotonic()
report = check(deck)
root = os.path.dirname(os.path.abspath(deck))


def rel(p):
    return Path(os.path.relpath(p, root)).as_posix()


out.write_text(json.dumps({
    "deck": str(deck),
    "counts": dict(Counter(d.code for d in report.diagnostics)),
    "diagnostics": [{"code": d.code, "severity": d.severity, "file": rel(d.path), "line": d.line}
                    for d in report.diagnostics[:200]],
    "not_checked": [{"what": n.what, "reasons": list(n.reasons), "count": n.count} for n in report.not_checked],
    "seconds": round(time.monotonic() - start, 1),
}), encoding="utf-8")
