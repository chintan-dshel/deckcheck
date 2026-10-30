"""DC005 unused definition (warning), spec §5: a MAT, SECTION or HOURGLASS that nothing refers to. Silent on a kind
wherever a use could be invisible (deckcheck.coverage.dc005_silent); the footer says why."""
from deckcheck.coverage import DC005_KINDS, dc005_silent
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index


def dc005(tree: Tree, ix: Index) -> list[Diagnostic]:
    silent = dc005_silent(tree, ix)
    out = []
    for kind in DC005_KINDS:
        if kind in silent:
            continue
        used = ix.used(kind)
        for id_, loc in sorted(ix.defs.get(kind, {}).items()):
            if id_ not in used:
                path, line, start, end = ix.where(loc)
                out.append(Diagnostic(path, line, start, end, "warning", "DC005",
                                      f"{kind} {id_} is defined but nothing refers to it"))
    return out
