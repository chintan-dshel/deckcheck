"""The command line (spec §6): deckcheck MAIN.k [MAIN2.k ...] [--format text|json] [--ignore CODE ...].
Formats reports; contains no checking logic. Exit 0: no errors; 1: an error; 2: could not run."""
import argparse
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from deckcheck.diagnostics import Report
from deckcheck.rules import CODES, check


def _version() -> str:
    try:
        return version("deckcheck")
    except PackageNotFoundError:
        return "unknown"


def _rel(path: Path) -> str:
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:  # another drive on Windows: relpath has no answer
        return Path(os.path.abspath(path)).as_posix()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _text(reports: list[Report]) -> str:
    lines = []
    for r in reports:
        for d in r.diagnostics:
            lines.append(f"{_rel(d.path)}:{d.line}:{d.start + 1}  {d.severity:<7}  {d.code}  {d.message}")
    errors = sum(d.severity == "error" for r in reports for d in r.diagnostics)
    warnings = sum(d.severity == "warning" for r in reports for d in r.diagnostics)
    if lines:
        lines += ["", f"{_plural(errors + warnings, 'problem')} ({_plural(errors, 'error')}, {_plural(warnings, 'warning')})"]
    else:
        lines.append("No problems found")
    for r in reports:
        head = "Not checked:" if len(reports) == 1 else f"Not checked ({_rel(r.main)}):"
        lines += ["", head]
        for n in r.not_checked:
            more = f" (+{n.count - len(n.reasons)} more)" if n.count > len(n.reasons) else ""
            lines.append(f"  {n.what}: {'; '.join(n.reasons)}{more}")
    return "\n".join(lines) + "\n"


def _json(reports: list[Report]) -> str:
    diags = [d for r in reports for d in r.diagnostics]
    return json.dumps({
        "version": 1,
        "diagnostics": [{"file": _rel(d.path), "line": d.line, "column": d.start + 1, "end_column": d.end + 1,
                         "severity": d.severity, "code": d.code, "message": d.message,
                         "related": [{"file": _rel(x.path), "line": x.line, "message": x.message} for x in d.related]}
                        for d in diags],
        "not_checked": [{"main": _rel(r.main), "what": n.what, "reasons": list(n.reasons), "count": n.count}
                        for r in reports for n in r.not_checked],
        "summary": {"errors": sum(d.severity == "error" for d in diags),
                    "warnings": sum(d.severity == "warning" for d in diags)},
    }, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deckcheck", description="Check keyword decks for LS-DYNA for structural "
                                     "mistakes: dangling references, duplicate ids, bad values, include problems.")
    parser.add_argument("decks", nargs="+", type=Path, metavar="MAIN.k", help="main deck; includes are followed")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--ignore", action="append", default=[], metavar="CODE", help="leave out a code (repeatable)")
    parser.add_argument("--version", action="version", version=f"deckcheck {_version()}")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # a path the console can't encode must not crash the run
    args = parser.parse_args(argv)
    ignore = {c.upper() for c in args.ignore}
    unknown = sorted(ignore - set(CODES))
    if unknown:
        parser.error(f"unknown code {unknown[0]} (known: {', '.join(CODES)})")
    for deck in args.decks:
        if not deck.is_file():
            print(f"deckcheck: {deck}: no such file", file=sys.stderr)
            return 2
    try:
        reports = [check(deck) for deck in args.decks]
    except Exception as e:  # outside any one block: deckcheck could not run (spec §6)
        print(f"deckcheck: internal error: {type(e).__name__}: {e} (please report this)", file=sys.stderr)
        return 2
    for r in reports:
        r.diagnostics[:] = [d for d in r.diagnostics if d.code not in ignore]
    sys.stdout.write(_json(reports) if args.format == "json" else _text(reports))
    return 1 if any(d.severity == "error" for r in reports for d in r.diagnostics) else 0
