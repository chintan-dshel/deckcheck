"""DC001 dangling reference (error) and DC006 accepted but no effect (warning), spec §5."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index, Ref


def _what(r: Ref) -> str:
    key, field = r.field.split(".", 1)
    if r.id == 0:  # a required reference left blank or 0 (index.REQUIRED)
        return f"*{key} {field} is blank or 0, but LS-DYNA requires a {r.kind} here ({r.kind} 0 does not exist)"
    return f"*{key} {field} refers to {r.kind} {r.id}, which is not defined"


def dc001(tree: Tree, ix: Index) -> list[Diagnostic]:
    missing = [p.name for p in tree.problems if p.kind == "missing"]
    note = ""
    if missing:
        note = f"; it may be defined in missing include '{missing[0]}'"
        if len(missing) > 1:
            note += f" or {len(missing) - 1} other missing include(s)"
    return [Diagnostic(r.path, r.line, r.start, r.end, "error", "DC001", _what(r) + note) for r in ix.dangling()]


def dc006(tree: Tree, ix: Index) -> list[Diagnostic]:
    return [Diagnostic(r.path, r.line, r.start, r.end, "warning", "DC006",
                       _what(r) + "; LS-DYNA accepts this, but the reference has no effect") for r in ix.ignored()]
