"""DC003 value or format problem (warning), spec §5: a value not of its field's type, a card containing a tab, cards
past a keyword's layout. LS-DYNA decided the rest (M1d Task 1): two values in one comma slot are read correctly
(torture m1d_mixed_free), so they are no finding; a value spilling into the next fixed field is a silent misread
(m1d_overflow_node) that needs every field of the card read to detect, so M1 reports it only where the spill
makes a value not of its type."""
import functools

from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import STRUCTURAL, Index
from deckcheck.keywords import layout

TAB = "tab in card: LS-DYNA misreads tab-separated cards (use spaces or commas)"


@functools.cache
def _has_text(key: str) -> bool:
    return any(c["kind"] in ("text", "include") for c in layout(key)["cards"])


def _field_cards(block) -> bool:
    """Cards LS-DYNA splits into fields: not the header or *TITLE, not text such as *COMMENT or a *DEFINE_FUNCTION
    body, not file names, and not a keyword the data doesn't cover (it passes through untouched, spec §4)."""
    return block.name not in STRUCTURAL and block.resolved is not None and not _has_text(block.resolved.name)


def dc003(tree: Tree, ix: Index) -> list[Diagnostic]:
    out, tab_lines = [], set()
    for fi, node in enumerate(tree.files):
        for block in node.source.blocks:
            if not _field_cards(block):
                continue
            for card in block.cards:
                if "\t" in card.text:
                    i = card.text.index("\t")
                    tab_lines.add((fi, card.line))
                    out.append(Diagnostic(node.path, card.line, i, i + 1, "warning", "DC003", TAB))
    for fi, p in ix.problems:
        if (fi, p.line) in tab_lines:  # the tab is the cause: one finding per card
            continue
        if p.kind == "bad":
            out.append(Diagnostic(tree.files[fi].path, p.line, p.start, p.end, "warning", "DC003",
                                  f"{p.detail}; LS-DYNA may misread this card"))
        elif p.kind == "extra":
            out.append(Diagnostic(tree.files[fi].path, p.line, p.start, p.end, "warning", "DC003", p.detail))
    for kind, key, loc, zero in ix.blank_defs:
        path, line, start, end = ix.where(loc)
        out.append(Diagnostic(path, line, start, end, "warning", "DC003",
                              f"*{key} defines a {kind} with {'id 0' if zero else 'a blank id'}, so nothing can refer to "
                              "it (LS-DYNA accepts it without a warning); if this card was pasted, check its columns"))
    return out
