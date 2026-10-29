"""*PARAMETER values for field substitution (spec §4, field reader row). A name whose value deckcheck can't know
for sure (an expression, a scoped parameter, a redefinition) maps to UNKNOWN, so nothing is checked against a guess."""
from deckcheck.conditions import UNKNOWN
from deckcheck.includes import Tree
from deckcheck.reader import Card

TYPES = {"R": float, "I": int, "C": str}


def _pairs(card: Card) -> list[tuple[str, str]]:
    if card.free:
        parts = [p.strip() for p in card.text.split(",")]
    else:
        parts = [card.text[k:k + 10].strip() for k in range(0, 80, 10)]
    return [(parts[k], parts[k + 1] if k + 1 < len(parts) else "") for k in range(0, len(parts), 2) if parts[k]]


def _typed(prmr: str, text: str) -> tuple[str, object]:
    kind, name = prmr[0].upper(), prmr[1:].strip().upper()
    try:
        return name, TYPES[kind](text)
    except (KeyError, ValueError):
        return name, UNKNOWN


def collect(tree: Tree) -> dict[str, object]:
    out: dict[str, object] = {}

    def put(name: str, value: object) -> None:
        old = out.get(name, value)
        out[name] = value if old is value or old == value else UNKNOWN

    for node in tree.files:
        for block in node.source.blocks:
            if block.name == "PARAMETER":
                for card in block.cards:
                    for prmr, text in _pairs(card):
                        put(*_typed(prmr, text))
            elif block.name == "PARAMETER_EXPRESSION":
                for card in block.cards:
                    prmr, _, expr = card.text.partition(",") if card.free else (card.text[:10], "", card.text[10:])
                    if prmr.strip():
                        put(*_typed(prmr.strip(), expr.strip()))
            elif block.name.startswith("PARAMETER"):
                for card in block.cards:
                    for prmr, _ in _pairs(card):
                        put(prmr[1:].strip().upper(), UNKNOWN)
    return out
