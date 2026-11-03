"""Navigation over a checked model (M2 spec §5.2-5.6, plan D4): definitions and uses by id from flat arrays kept
after a check, and the fields under a position, re-read from the one block there. No LSP types: M3 reuses this."""
import itertools
import struct
from array import array
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from deckcheck.includes import Tree, _key
from deckcheck.index import LOOKUP, Index, unpack

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
