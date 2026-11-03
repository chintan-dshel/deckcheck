"""Navigation over a checked model (M2 spec §5.2-5.6, plan D4): definitions and uses by id from flat arrays kept
after a check, and the fields under a position, re-read from the one block there. No LSP types: M3 reuses this."""
import bisect
import itertools
import struct
from array import array
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from deckcheck.definers import definers
from deckcheck.fields import Field, is_long, read_fields
from deckcheck.includes import Tree, _key
from deckcheck.index import LOOKUP, Index, _file_offsets, _shift, _span, target, unpack
from deckcheck.keywords import layout
from deckcheck.reader import Block, Card, SourceFile

CHUNK = 20_000  # as lsp.workspace.CHUNK: a C-level loop over more holds the GIL long enough to stall requests
LOW = (1 << 64) - 1


class Loc(NamedTuple):
    fi: int
    path: Path
    line: int
    start: int
    end: int


@dataclass
class Table:
    """One kind's definitions or references: ids as int64 bytes (searched with bytes.find, no object per id)."""
    ids: bytearray
    files: array  # "H"
    locs: array   # "q", pack(0, line, start, end)

    def find(self, id_: int) -> Iterator[int]:
        needle, pos = struct.pack("=q", id_), 0
        while (pos := self.ids.find(needle, pos)) != -1:
            if pos % 8 == 0:
                yield pos // 8
                pos += 8
            else:  # a match across two ids
                pos += 1

    def loc(self, i: int, tree: Tree) -> Loc:
        _, line, start, end = unpack(self.locs[i])
        fi = self.files[i]
        return Loc(fi, tree.files[fi].path, line, start, end)


def _table(pairs) -> Table:
    """(id, packed loc with file) pairs, consumed a chunk at a time."""
    ids, files, locs = array("q"), array("H"), array("q")
    it = iter(pairs)
    while chunk := list(itertools.islice(it, CHUNK)):
        for id_, loc in chunk:
            ids.append(id_)
            files.append(loc >> 64)
            locs.append(loc & LOW)
    return Table(bytearray(ids.tobytes()), files, locs)


@dataclass
class NavIndex:
    tree: Tree
    params: dict
    long_deck: bool
    defs: dict[str, Table] = field(default_factory=dict)
    refs: dict[str, Table] = field(default_factory=dict)
    uncertain_defs: dict[str, set[str]] = field(default_factory=dict)
    uncertain_uses: dict[str, set[str]] = field(default_factory=dict)
    possible: set[str] = field(default_factory=set)  # kinds with uses deckcheck counts but can't place
    blind: bool = False
    _files: dict[str, int] = field(default_factory=dict)

    def file_index(self, path: Path) -> int | None:
        return self._files.get(_key(path))

    def checked(self, kind: str) -> bool:
        return not self.blind and not any(k in self.uncertain_defs for k in LOOKUP.get(kind, (kind,)))

    def _defined(self, kind: str, id_: int) -> bool:
        t = self.defs.get(kind)
        return t is not None and next(t.find(id_), None) is not None

    def owner(self, kind: str, id_: int) -> str:
        """The kind a reference of `kind` to `id_` resolves to: the first LS-DYNA looks in that defines it (a part
        set id with no such set falls back to the part)."""
        order = LOOKUP.get(kind, (kind,))
        return next((c for c in order if self._defined(c, id_)), order[0])

    def definitions(self, kind: str, id_: int) -> list[Loc]:
        """Every definition the id resolves to (a duplicate has several), the first one first."""
        t = self.defs.get(self.owner(kind, id_))
        return [t.loc(i, self.tree) for i in t.find(id_)] if t else []

    def uses(self, kind: str, id_: int) -> list[Loc]:
        """Every placed reference that resolves to this definition kind and id."""
        out = []
        for k, t in self.refs.items():
            if kind in LOOKUP.get(k, (k,)) and self.owner(k, id_) == kind:
                out.extend(t.loc(i, self.tree) for i in t.find(id_))
        return sorted(set(out), key=lambda l: (str(l.path), l.line, l.start))

    def uses_complete(self, kind: str) -> list[str]:
        why = []
        for k in {k for k in set(self.uncertain_uses) | self.possible if kind in LOOKUP.get(k, (k,))}:
            why += sorted(self.uncertain_uses.get(k, ())) or [f"{k}: uses deckcheck counts but can't place"]
        return why


def build_nav(ix: Index) -> NavIndex:
    """Worker thread, after the rules ran: the index's dicts become flat tables (about 18 bytes per id instead of
    about 100). The reference arrays are shared with the index, so the caller may drain it afterwards."""
    nav = NavIndex(ix.tree, dict(ix.params), ix.long_deck,
                   uncertain_defs={k: set(v) for k, v in ix.uncertain_defs.items()},
                   uncertain_uses={k: set(v) for k, v in ix.uncertain_uses.items()},
                   possible=set(ix.possible), blind=bool(ix.blind),
                   _files={_key(f.path): i for i, f in enumerate(ix.tree.files)})
    later: dict[str, list[tuple[int, int]]] = {}
    for kind, id_, loc, _ in ix.dups:
        later.setdefault(kind, []).append((id_, loc))
    for kind, d in ix.defs.items():
        nav.defs[kind] = _table(itertools.chain(d.items(), later.get(kind, ())))
    unchecked: dict[str, list[tuple[int, int]]] = {}
    for kind, id_, loc, _ in ix.unchecked:
        unchecked.setdefault(kind, []).append((id_, loc))
    for kind in set(ix.refs) | set(unchecked):
        ids, files, locs, _ = ix.refs.get(kind, (array("q"), array("H"), array("q"), array("H")))
        extra = _table(unchecked.get(kind, ()))
        nav.refs[kind] = Table(bytearray(ids.tobytes()) + extra.ids, files + extra.files, locs + extra.locs)
    return nav


READ_LIMIT = 2000  # cards read from a block's start to reach a position (D5): about 40 ms


def block_at(src: SourceFile, line: int) -> Block | None:
    i = bisect.bisect_right(src.blocks, line, key=lambda b: b.line) - 1
    if i < 0:
        return None
    b = src.blocks[i]
    return b if line == b.line or card_at(b, line) is not None else None


def card_at(block: Block, line: int) -> Card | None:
    i = bisect.bisect_left(block.cards, line, key=lambda c: c.line)
    return block.cards[i] if i < len(block.cards) and block.cards[i].line == line else None


def line_text(src: SourceFile, line: int) -> str | None:
    b = block_at(src, line)
    if b is None:
        return None
    return b.text if line == b.line else card_at(b, line).text


def _row_cards(block: Block) -> int:
    """Cards per row when every card of the block is a row of one table: then a row can be read alone. 0 if not."""
    opts = set(block.resolved.options)
    cards = [c for c in layout(block.resolved.name)["cards"] if c["option"] is None or c["option"] in opts]
    if len(cards) != 1 or cards[0].get("when") or cards[0].get("length"):
        return 0
    c = cards[0]
    if c["kind"] == "table":
        return 1
    if c["kind"] == "table_group" and all(s["kind"] == "card" and not s.get("when") for s in c["cards"]):
        return len(c["cards"])
    return 0


def fields_between(block: Block, first: int, last: int, params: dict, long_deck: bool) -> list[Field] | None:
    if block.resolved is None:
        return None
    n = _row_cards(block)
    if n:
        out = []
        i = bisect.bisect_left(block.cards, first, key=lambda c: c.line)
        i -= i % n
        while i < len(block.cards) and block.cards[i].line <= last:
            row = Block(block.name, block.line, block.resolved, block.cards[i:i + n], block.text)
            out += [f for f in read_fields(row, params, long_deck) if first <= f.line <= last]
            i += n
        return out
    out, seen, previous = [], 0, None
    for f in read_fields(block, params, long_deck):
        if f.line > last:
            break
        if f.line < first:
            if f.line != previous:
                seen, previous = seen + 1, f.line
                if seen > READ_LIMIT:
                    return None
            continue
        out.append(f)
    return out


def hit(fields: list[Field], col: int) -> Field | None:
    for f in fields:
        start, end = _span(f)
        if start <= col < max(end, start + 1):
            return f
    return None


def _row(fields: list[Field], f: Field) -> dict[str, Field]:
    return {x.name: x for x in fields if x.group == f.group}


def _key_of(nav: NavIndex, fi: int, f: Field) -> str | None:
    b = block_at(nav.tree.files[fi].source, f.line)
    return b.resolved.name if b is not None and b.resolved else None


def subject(nav: NavIndex, fi: int, fields: list[Field], f: Field) -> tuple[str, int, bool] | None:
    offs = _file_offsets(nav.tree, fi)
    for kind, idf in definers().get(_key_of(nav, fi, f), ()):
        if f.name == idf and isinstance(f.value, int) and f.value > 0:
            shift = _shift(kind, offs)
            return None if shift is None else (kind, f.value + shift, True)
    t = target(f, _row(fields, f), offs)
    return (t.kind, t.id, False) if t.how in ("checked", "unchecked", "possible") else None


TYPES = {"int": "integer", "float": "real", "str": "text", "bool": "flag"}


def _where(nav: NavIndex, loc: Loc) -> str:
    b = block_at(nav.tree.files[loc.fi].source, loc.line)
    return f"*{b.name} at {loc.path.name}:{loc.line}" if b else f"{loc.path.name}:{loc.line}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def explain(nav: NavIndex, fi: int, fields: list[Field], f: Field | None) -> str | None:
    """Structure and resolved references only; no descriptions (spec §2, §5.2)."""
    if f is None:
        return None
    spec = f.spec
    block = block_at(nav.tree.files[fi].source, f.line)
    card = card_at(block, f.line)
    head = [f"**{f.name}**"]
    if "offset" in spec and "width" in spec and not card.free and not is_long(block, nav.long_deck):
        head.append(f"columns {spec['offset'] + 1}-{spec['offset'] + spec['width']}")
    head.append(TYPES.get(spec.get("type"), spec.get("type") or ""))
    if spec.get("default") is not None:
        head.append(f"default: {spec['default']}")
    lines = [" · ".join(h for h in head if h)]
    raw = card.text[f.start:f.end]
    if f.value is None:
        lines.append("blank")
    elif raw.startswith(("&", "-&")):
        lines.append(f"{raw} = {f.value}")
    else:
        lines.append(f"read as {f.value}")
    s = subject(nav, fi, fields, f)
    if s is None:
        t = target(f, _row(fields, f), _file_offsets(nav.tree, fi))
        if t.how in ("unmapped", "unknown", "not an id", "offset"):
            lines.append(f"a reference deckcheck can't resolve ({t.how})")
        return "\n\n".join(lines)
    kind, id_, is_def = s
    if isinstance(f.value, int) and abs(f.value) != id_:
        lines.append(f"{kind} {id_} (offset {id_ - abs(f.value)} from *INCLUDE_TRANSFORM)")
    if is_def:
        others = [l for l in nav.definitions(kind, id_) if (l.fi, l.line) != (fi, f.line)]
        uses = nav.uses(kind, id_)
        lines.append(f"Defines {kind} {id_}; {_plural(len(uses), 'use')}")
        lines += [f"also defined at {l.path.name}:{l.line}" for l in others]
        why = nav.uses_complete(kind)
        if why:
            lines.append("some uses can't be placed: " + "; ".join(why[:3]))
        return "\n\n".join(lines)
    found = nav.definitions(kind, id_)
    if found:
        lines += [f"{f.name} → {kind} {id_}, {_where(nav, l)}" for l in found]
    elif f.spec.get("link_when") == "unchecked":
        lines.append(f"{kind} {id_} is not defined: LS-DYNA accepts this, but the reference has no effect")
    elif nav.checked(kind):
        lines.append(f"{kind} {id_} is not defined")
    else:
        why = sorted(nav.uncertain_defs.get(kind, ())) or ["the model was not fully read"]
        lines.append(f"{kind} {id_} not found; not checked: " + "; ".join(why[:3]))
    return "\n\n".join(lines)


def explain_keyword(block: Block) -> str:
    if block.resolved is None:
        return f"*{block.name}: not in deckcheck's keyword data; passed through"
    r = block.resolved
    opts = f", options {', '.join(r.options)}" if r.options else ""
    return f"*{block.name}: keyword {r.name}{opts}" + (f", format {r.format}" if r.format else "")
