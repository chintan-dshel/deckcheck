"""DC004 include problem (error), spec §5: a missing file or a circular include, from the resolver."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index

MESSAGES = {"missing": "include file '{}' not found", "cycle": "include '{}' is circular: it includes itself"}


def dc004(tree: Tree, ix: Index) -> list[Diagnostic]:
    return [Diagnostic(p.file, p.line, p.columns[0], p.columns[1], "error", "DC004", MESSAGES[p.kind].format(p.name))
            for p in tree.problems if p.kind in MESSAGES]
