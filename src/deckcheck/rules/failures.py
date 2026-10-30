"""DC000: deckcheck itself failed on a block (spec §6: one diagnostic, the run continues). Its kinds are listed
under "Not checked"; the warning asks for a report, because it is a deckcheck bug, not a deck mistake."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index


def dc000(tree: Tree, ix: Index) -> list[Diagnostic]:
    return [Diagnostic(tree.files[fi].path, line, 0, 1, "warning", "DC000",
                       f"deckcheck could not read {text}; this block is not checked (please report this)")
            for fi, line, text in ix.failures]
