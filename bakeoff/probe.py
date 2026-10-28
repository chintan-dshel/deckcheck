"""Measure dynars on one deck: parse, the four built-in rules, line accuracy, round-trip, one edit."""
import json
import sys
import time
from pathlib import Path

import dynars
from dynars import Rule

RULES = [Rule.references_resolve, Rule.duplicate_ids, Rule.include_missing, Rule.unreferenced_entities]


def clean_path(p: str) -> str:
    return p[4:] if p.startswith("\\\\?\\") else p


def _line_at(path: str, n: int) -> str:
    if n < 1 or not Path(path).exists():
        return ""
    with open(path, "rb") as f:
        for i, raw in enumerate(f, 1):
            if i == n:
                return raw.decode("latin-1").rstrip("\r\n")
    return ""


def _line_ok(file: str, line: int, keyword: str) -> bool:
    return _line_at(file, line).upper().startswith("*" + keyword.upper())


def _round_trip(deck) -> dict:
    same = [Path(clean_path(f.path)).read_bytes() == f.to_bytes() for f in deck.files()]
    return {"files": len(same), "identical": sum(same)}


def _one_edit(deck) -> dict:
    parts = deck.keywords("PART")
    if not parts:
        return {"tried": False}
    kw = parts[0]
    owner = next(f for f in deck.files() if clean_path(f.path) == clean_path(kw.file))
    before = owner.to_bytes().splitlines()
    status = kw.set_field("grav", (kw.field("grav") or 0) + 1)
    after = owner.to_bytes().splitlines()
    changed = sum(a != b for a, b in zip(before, after)) + abs(len(before) - len(after))
    return {"tried": True, "status": status, "changed_lines": changed}


def measure(deck_path: str) -> dict:
    try:
        t0 = time.perf_counter()
        deck = dynars.parse_deck(deck_path)
        t1 = time.perf_counter()
        report = deck.validate([make() for make in RULES])
        t2 = time.perf_counter()
        findings = []
        for f in report.findings:
            file = clean_path(f.file)
            findings.append({"rule": f.rule, "severity": repr(f.severity).split(".")[-1], "file": file,
                             "line": f.line, "keyword": f.keyword, "message": f.message,
                             "line_ok": _line_ok(file, f.line, f.keyword)})
        return {"deck": deck_path, "files": len(deck.files()), "parse_s": round(t1 - t0, 3),
                "rules_s": round(t2 - t1, 3), "findings": findings, "round_trip": _round_trip(deck),
                "edit": _one_edit(deck)}
    except Exception as e:  # measurement must record failures, not crash the run
        return {"deck": deck_path, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    result = measure(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")
