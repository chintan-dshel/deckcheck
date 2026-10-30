"""Run every check on one main deck (spec §5). A rule is a function (tree, index) -> list[Diagnostic]; adding a
check is adding a module here and a line to RULES."""
from pathlib import Path

from deckcheck.coverage import not_checked
from deckcheck.diagnostics import Report
from deckcheck.includes import resolve_tree
from deckcheck.index import build
from deckcheck.rules.duplicates import dc002
from deckcheck.rules.failures import dc000
from deckcheck.rules.include_files import dc004
from deckcheck.rules.references import dc001, dc006
from deckcheck.rules.unused import dc005
from deckcheck.rules.values import dc003

CODES = ("DC000", "DC001", "DC002", "DC003", "DC004", "DC005", "DC006")
RULES = [dc000, dc001, dc002, dc003, dc004, dc005, dc006]


def check(main: Path, source=None, cache=None) -> Report:
    tree = resolve_tree(main, source, cache)
    ix = build(tree)
    found = [d for rule in RULES for d in rule(tree, ix)]
    found.sort(key=lambda d: (str(d.path), d.line, d.start, d.code))
    return Report(main, found, not_checked(tree, ix), tree, ix)
