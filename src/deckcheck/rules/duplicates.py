"""DC002 duplicate id, spec §5. Severity per kind from LS-DYNA (bakeoff/results/m1d_referee.txt, M1d Task 1):
a kind LS-DYNA rejects twice-defined is an error; one it accepts is a warning naming the definition it uses.
A kind not tested is reported as a warning that says so, never as a confirmed error."""
from pathlib import Path

from deckcheck.diagnostics import Diagnostic, Related
from deckcheck.fields import is_long
from deckcheck.includes import Tree
from deckcheck.index import Index, _long_deck

# m1d_dup_part (Error 10176), m1d_dup_mat and m1d_dup_section (10137), m1d_dup_curve (10173), m1d_dup_node_set (10110)
REJECTED: frozenset[str] = frozenset({"PART", "MAT", "SECTION", "DEFINE_CURVE", "SET_NODE"})
ACCEPTED_DUPLICATES: dict[str, str] = {}  # kind -> "first" | "last" | "unknown"; no tested kind is accepted
# NODE: rejected at different coordinates (m1d_dup_node, Error 11168), accepted at identical ones (m1d_dup_node_same)


def _transformed(tree: Tree, fi: int) -> bool:
    """Brought in, directly or through an ancestor, by *INCLUDE_TRANSFORM (its offsets dict is set even when all zero):
    a translation or scaling moves the nodes, and deckcheck does not apply it."""
    i = fi
    while i is not None:
        if tree.files[i].offsets:
            return True
        i = tree.files[i].parent
    return False


def _node_cards(tree: Tree) -> dict[tuple[Path, int], str | None]:
    """Each *NODE card's text by (file, line), or None where the coordinates can't be trusted at 8/16/16/16:
    a long-format block (+ suffix or LONG=Y) or a transformed file."""
    long_deck, out = _long_deck(tree), {}
    for fi, node in enumerate(tree.files):
        moved = _transformed(tree, fi)
        for block in node.source.blocks:
            if block.resolved is not None and block.resolved.name == "NODE":
                trusted = not moved and not is_long(block, long_deck)
                for card in block.cards:
                    out[(node.path, card.line)] = card.text if trusted else None
    return out


def _coords(text: str | None) -> tuple[float, ...] | None:
    """A standard-width *NODE card's x, y, z: columns 8-56 (16 wide each), or the comma slots after the id. None if
    unreadable, which includes Fortran D exponents and *PARAMETER references: deckcheck then doesn't compare."""
    if text is None:
        return None
    parts = text.split(",")[1:4] if "," in text else [text[8:24], text[24:40], text[40:56]]
    try:
        values = [float(p) if p.strip() else 0.0 for p in parts]
    except ValueError:
        return None
    return tuple(values + [0.0] * (3 - len(values)))


def _node(cards: dict, d, head: str) -> tuple[str, str]:
    a, b = _coords(cards.get((d.first_path, d.first_line))), _coords(cards.get((d.path, d.line)))
    if a is None or b is None:  # compared only when both cards are standard width, untransformed and readable
        return "warning", (f"{head}; LS-DYNA rejects this if the coordinates differ and accepts it if they match "
                           "(deckcheck could not compare them)")
    if a == b:
        return "warning", f"{head} at the same coordinates; LS-DYNA accepts this"
    return "error", f"{head} at different coordinates"


def dc002(tree: Tree, ix: Index) -> list[Diagnostic]:
    out, cards = [], None
    for d in ix.duplicates():
        head = f"{d.kind} {d.id} is defined twice (first at {d.first_path.name}:{d.first_line})"
        related = (Related(d.first_path, d.first_line, "first definition"),)
        if d.kind == "NODE":
            cards = _node_cards(tree) if cards is None else cards  # built once, on the first node duplicate
            severity, message = _node(cards, d, head)
        elif d.kind in REJECTED:
            severity, message = "error", head
        elif d.kind in ACCEPTED_DUPLICATES:
            wins = ACCEPTED_DUPLICATES[d.kind]
            tail = (f"LS-DYNA accepts this and uses the {wins} definition" if wins in ("first", "last")
                    else "LS-DYNA accepts this; which definition it uses is not known")
            severity, message = "warning", f"{head}; {tail}"
        else:
            severity, message = "warning", f"{head}; not tested whether LS-DYNA rejects this"
        out.append(Diagnostic(d.path, d.line, d.start, d.end, severity, "DC002", message, related))
    return out
