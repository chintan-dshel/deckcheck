"""Field values of a keyword block, by the keyword data's layout (deckcheck.keywords.layout): option-card
placement, tables, series and card sets, conditional cards (deckcheck.conditions), long and free format, and
*PARAMETER substitution (spec §4, field reader row). Where it can't decide, it stops and says so (`unread`)."""
import functools
import itertools
import re
from typing import Iterator, NamedTuple

from deckcheck.conditions import UNKNOWN, Scope, compile_expr, evaluate, names_in
from deckcheck.keywords import layout, walk_cards
from deckcheck.reader import Block, Card


LONG_KEYWORD = True  # long_keyword: *KEYWORD LONG=Y makes every card long (LONG=S is the standard format)
LONG_WIDTH = 20      # pydyna's to_long: each field max(width, 20), one line per card (long_section)
OPTIONAL_TRAILING = frozenset("ABCDEFG")  # contact optional cards A-G: read when present (pydyna: post options)
REPEAT_INSTANCES = True  # repeat_velocity, repeat_history_id, repeat_load_node_set, repeat_mat: cards left after the
                         # layout start another instance
FLAG_TRUE = "&"  # pydyna Flag(True, "&", ""): the only bool field, mpp2, marks the MPP card 2 that follows
# pydyna writes these optional cards only when set; its reader reads the card, then keeps it if set (lib/cards.py
# _read_card). LS-DYNA reads them by position, so deckcheck reads one whenever a card remains.
HAS_VALUES = re.compile(r"self\._cards\[\d+\]\.has_nondefault_values\(\)( or self\._cards\[\d+\]\.active)?")


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


class Field(NamedTuple):
    name: str
    line: int
    start: int
    end: int
    value: object  # int | float | str | None (blank) | UNKNOWN (undefined *PARAMETER, bad value)
    group: int     # fields read from the same card share a group
    spec: dict     # the field's (or series') layout entry, with its link facts


class FieldProblem(NamedTuple):
    kind: str      # "unread": the rest of the block from here; "extra": cards past the layout; "bad": not its type
    line: int
    start: int
    end: int
    detail: str


def _parse(text: str, ftype: str, params: dict) -> object:
    """A field's value; raises ValueError when the text is not of the field's type."""
    if not text:
        return None
    if ftype == "bool":
        return text == FLAG_TRUE
    if text.startswith(("&", "-&")):
        value = params.get(text.lstrip("-&").strip().upper(), UNKNOWN)
        if text.startswith("-"):
            value = -value if isinstance(value, (int, float)) else UNKNOWN
        if ftype == "int" and isinstance(value, float) and value.is_integer():
            value = int(value)
        return value
    if ftype == "int":
        try:
            return int(text)
        except ValueError:
            number = float(text)
            if number.is_integer():
                return int(number)
            raise
    if ftype == "float":
        return float(text)
    return text


def _free_parts(text: str) -> list[tuple[str, int]]:
    out, at = [], 0
    for raw in text.split(","):
        out.append((raw, at))
        at += len(raw) + 1
    return out


@functools.cache
def _positions(key: str) -> dict[str, tuple[str, int]]:
    out = {}
    for o in layout(key)["options"]:
        placement, _, index = o["position"].partition("/")
        out[o["name"]] = (placement, int(index))
    return out


@functools.cache
def _needed(key: str) -> frozenset[str]:
    """Field names some condition or length of this keyword reads: always parsed into the scope."""
    texts = [c.get(k) for c in walk_cards(layout(key)["cards"]) for k in ("when", "length")]
    return frozenset(n for t in texts if t for n in names_in(t))


def _ordered(cards: list[dict], key: str, options: frozenset[str], top: bool) -> list[dict]:
    """Cards in reading order (pydyna card_position): pre options, pre/2 before pre/1; main cards and main-placed
    options in data order; post options ascending. Unnamed contact cards A-G are read when cards remain."""
    pos = _positions(key)

    def place(c):
        return pos.get(c["option"], ("main", 0)) if c["option"] else ("main", 0)

    pre = sorted((c for c in cards if c["option"] in options and place(c)[0] == "pre"), key=lambda c: -place(c)[1])
    main = [c for c in cards if c["option"] is None or (c["option"] in options and place(c)[0] == "main")]
    post = sorted((c for c in cards if place(c)[0] == "post"
                   and (c["option"] in options or (top and c["option"] in OPTIONAL_TRAILING))),
                  key=lambda c: place(c)[1])
    return pre + main + post


class _Reader:
    def __init__(self, block: Block, params: dict, long: bool, wanted, problems: list):
        self.block, self.cards, self.i, self.group = block, block.cards, 0, 0
        self.key = block.resolved.name
        self.options = frozenset(block.resolved.options)
        self.params, self.long, self.wanted, self.problems = params, long, wanted, problems
        self.needed = _needed(self.key)
        self.stopped = False

    def left(self) -> bool:
        return not self.stopped and self.i < len(self.cards)

    def stop(self, reason: str) -> None:
        line = self.cards[self.i].line if self.i < len(self.cards) else self.block.line
        self.problems.append(FieldProblem("unread", line, 0, 0, reason))
        self.stopped = True

    def active(self, spec: dict, scope: Scope) -> bool:
        if spec.get("when") is None:
            return True
        tree = compile_expr(spec["when"])
        v = evaluate(tree, scope) if tree else UNKNOWN
        if v is UNKNOWN:
            self.stop(f"condition {spec['when']!r} undecided")
            return False
        return bool(v)

    def count(self, spec: dict, scope: Scope):
        """Rows, items or elements to read; None for unbounded. Stops the block when undecidable."""
        if spec.get("length") is None:
            return None
        tree = compile_expr(spec["length"])
        v = evaluate(tree, scope) if tree else UNKNOWN
        if v is UNKNOWN or not isinstance(v, (int, float)):
            self.stop(f"length {spec['length']!r} undecided")
            return 0
        return max(int(v), 0)

    def decided_after(self, spec: dict) -> bool:
        """A card whose condition reads only its own fields, or pydyna's has-values chain: pydyna reads the card,
        then decides (lib/cards.py _read_card), so deckcheck does too."""
        when = spec.get("when")
        if spec["kind"] != "card" or when is None:
            return False
        names = names_in(when)
        return bool(HAS_VALUES.fullmatch(when)) or bool(names) and names <= {f["name"] for f in spec["fields"]}

    def tentative(self, spec: dict, scope: Scope) -> Iterator[Field]:
        when = spec["when"]
        if HAS_VALUES.fullmatch(when):
            yield from self.card(spec["fields"], scope)
            return
        i, group, n_problems, values = self.i, self.group, len(self.problems), dict(scope.values)
        out = list(self.card(spec["fields"], scope))
        tree = compile_expr(when)
        v = evaluate(tree, scope) if tree else UNKNOWN
        if v is not UNKNOWN and v:
            yield from out
            return
        self.i, self.group = i, group  # not this card: put it back
        del self.problems[n_problems:]
        scope.values.clear()
        scope.values.update(values)
        if v is UNKNOWN:
            self.stop(f"condition {when!r} undecided")

    def container(self, cards: list[dict], scope: Scope, top: bool) -> Iterator[Field]:
        for spec in _ordered(cards, self.key, self.options, top):
            if self.left() and "stop" in spec:
                self.stop(spec["stop"])
                return
            if self.left() and self.decided_after(spec):
                yield from self.tentative(spec, scope)
                if self.stopped:
                    return
                continue
            if not self.left() or not self.active(spec, scope):
                if self.stopped:
                    return
                continue
            kind = spec["kind"]
            if kind == "card":
                yield from self.card(spec["fields"], scope)
            elif kind == "table":
                n = self.count(spec, scope)
                for _ in itertools.count() if n is None else range(n):
                    if not self.left():
                        break
                    yield from self.card(spec["fields"], scope)
            elif kind == "table_group":
                n = self.count(spec, scope)
                for _ in itertools.count() if n is None else range(n):
                    if not self.left():
                        break
                    for sub in spec["cards"]:
                        if self.left() and self.active(sub, scope):
                            yield from self.card(sub["fields"], scope)
            elif kind == "series":
                yield from self.series(spec, scope)
            elif kind == "card_set":
                n = self.count(spec, scope)
                for _ in itertools.count() if n is None else range(n):
                    before = self.i
                    if not self.left():
                        break
                    yield from self.container(spec["cards"], Scope(scope), False)
                    if self.i == before:
                        break
            else:  # text, include: free text to the end of the block
                self.i = len(self.cards)

    def take(self, name: str) -> bool:
        return self.wanted is None or name in self.wanted

    def parse(self, raw: str, at: int, spec: dict, ftype: str, line: int, scope: Scope | None) -> Field:
        v = _value(raw, at)
        try:
            parsed = _parse(v.text, ftype, self.params)
        except ValueError:
            self.problems.append(FieldProblem("bad", line, v.start, v.end, f"{spec.get('name')}: {v.text!r} is not {ftype}"))
            parsed = UNKNOWN
        if scope is not None:
            scope.values[spec["name"]] = spec.get("default") if parsed is None else parsed
        return Field(spec["name"], line, v.start, v.end, parsed, self.group, spec)

    def card(self, specs: list[dict], scope: Scope) -> Iterator[Field]:
        card: Card = self.cards[self.i]
        self.i += 1
        self.group += 1
        parts = _free_parts(card.text) if card.free else None
        at = 0
        for n, f in enumerate(specs):
            width = max(f["width"], LONG_WIDTH) if self.long else f["width"]
            offset = at if self.long else f["offset"]
            at += width
            name = f["name"]
            if not self.take(name) and name not in self.needed:
                continue
            if parts is not None:
                raw, pos = parts[n] if n < len(parts) else ("", len(card.text))
            else:
                raw, pos = card.text[offset:offset + width], offset
            field = self.parse(raw, pos, f, f["type"], card.line, scope)
            if self.take(name):
                yield field

    def series(self, spec: dict, scope: Scope) -> Iterator[Field]:
        if self.long:
            self.stop("long-format series")  # no LS-DYNA case for its element width yet
            return
        n = self.count(spec, scope)
        if self.stopped:
            return
        width, per, done = spec["element_width"], spec["per_card"], 0
        while self.left() and (n is None or done < n):
            card = self.cards[self.i]
            self.i += 1
            self.group += 1
            raws = _free_parts(card.text) if card.free else [(card.text[k * width:(k + 1) * width], k * width)
                                                             for k in range(per)]
            for raw, at in raws:
                if n is not None and done >= n:
                    break
                if n is None and not raw.strip():
                    continue  # an unbounded list's blank slots are empty, not elements
                done += 1
                if self.take(spec["name"]):
                    yield self.parse(raw, at, spec, spec["type"], card.line, None)


def is_long(block: Block, long_deck: bool) -> bool:
    fmt = block.resolved.format
    return fmt == "+" or (long_deck and fmt != "-")


def read_fields(block: Block, params: dict | None = None, long_deck: bool = False, wanted=None,
                problems: list | None = None) -> Iterator[Field]:
    """Every field of a resolved block in reading order (only `wanted` names, if given). Problems go to
    `problems`. An unresolved block yields nothing: it passes through untouched (spec §4)."""
    if block.resolved is None:
        return
    problems = [] if problems is None else problems
    reader = _Reader(block, params or {}, is_long(block, long_deck), wanted, problems)
    entry = layout(block.resolved.name)
    cards, legacy = entry["cards"], entry.get("legacy")
    first = next((c for c in block.cards if c.text.strip()), None)
    if legacy and first is not None and len(first.text.strip()) > legacy["first_card_longer_than"]:
        cards = legacy["cards"]  # pydyna before_read: the one-line legacy format
    yield from reader.container(cards, Scope(), True)
    while REPEAT_INSTANCES and not reader.stopped and any(c.text.strip() for c in block.cards[reader.i:]):
        before = reader.i
        yield from reader.container(cards, Scope(), True)
        if reader.i == before:
            break
    if not reader.stopped:
        rest = [c for c in block.cards[reader.i:] if c.text.strip()]
        if rest:
            problems.append(FieldProblem("extra", rest[0].line, 0, len(rest[0].text.rstrip()),
                                         f"{len(rest)} card(s) past the layout"))
