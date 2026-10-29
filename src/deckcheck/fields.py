"""Field values of a card, by the keyword data's column layout (fixed format) or by comma position (free format).
M1c extends this into the full field reader (long format, *PARAMETER substitution, conditional cards)."""
from typing import NamedTuple

from deckcheck.reader import Card


class Value(NamedTuple):
    text: str   # stripped
    start: int  # 0-based column span of the stripped text: [start, end)
    end: int


def _value(raw: str, at: int) -> Value:
    lead = len(raw) - len(raw.lstrip())
    return Value(raw.strip(), at + lead, at + len(raw.rstrip()))


def card_values(card: Card, fields: list[dict]) -> dict[str, Value]:
    if card.free:
        out, at = {}, 0
        for f, raw in zip(fields, card.text.split(",")):
            out[f["name"]] = _value(raw, at)
            at += len(raw) + 1
        return out
    return {f["name"]: _value(card.text[f["offset"]:f["offset"] + f["width"]], f["offset"]) for f in fields}
