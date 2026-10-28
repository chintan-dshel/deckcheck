"""Field values of a card, by the keyword data's column layout (fixed format) or by comma position (free format).
M1c extends this into the full field reader (long format, *PARAMETER substitution, conditional cards)."""
from deckcheck.reader import Card


def card_values(card: Card, fields: list[dict]) -> dict[str, str]:
    if card.free:
        parts = card.text.split(",")
        return {f["name"]: parts[i].strip() for i, f in enumerate(fields) if i < len(parts)}
    return {f["name"]: card.text[f["offset"]:f["offset"] + f["width"]].strip() for f in fields}
