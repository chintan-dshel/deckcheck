"""Definitions and references of every entity kind across a deck's include tree (spec §4, index row). Ids are
shifted by *INCLUDE_TRANSFORM offsets; wherever deckcheck can't see all of a kind's definitions or uses, the kind is
marked uncertain and M1d's rules stay silent on it (spec §3: zero false alarms)."""
import functools
import itertools
from array import array
from dataclasses import dataclass, field
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple

from deckcheck.conditions import UNKNOWN
from deckcheck.definers import definers, family_kind, not_definer
from deckcheck.fields import LONG_KEYWORD, Field, FieldProblem, read_fields
from deckcheck.includes import Tree
from deckcheck.keywords import layout, walk_cards
from deckcheck.params import collect

# kind -> the *INCLUDE_TRANSFORM field LS-DYNA shifts it by (bakeoff/results/m1c_probes.json, M1c Task 1)
OFFSET_FIELD: dict[str, str] = {
    "MAT": "idmoff",
    "SECTION": "idroff",
    "HOURGLASS": "idroff",
    "NODE": "idnoff",
    "DEFINE_CURVE": "idfoff",
    "PART": "idpoff",
    "SET_PART": "idsoff",
    "SET_NODE": "idsoff",
    "ELEMENT_SHELL": "ideoff",
    "SET_SEGMENT": "idsoff",
}
# a reference of the key kind resolves against definitions of any listed kind: curves and tables share ids; a
# missing part set id falls back to the part with that id (torture contact_type2_bad/_none, velocity_styp1_bad/_none)
LOOKUP = {"DEFINE_CURVE": ("DEFINE_CURVE", "DEFINE_TABLE"), "DEFINE_CURVE_OR_TABLE": ("DEFINE_CURVE", "DEFINE_TABLE"),
          "SET_PART": ("SET_PART", "PART"), "ICFD_PART": ("ICFD_PART", "ICFD_PART_VOL")}
ID_MAX = 2**63 - 1  # array('q')
STRUCTURAL = frozenset({"KEYWORD", "TITLE", "END"})


def pack(file: int, line: int, start: int, end: int) -> int:
    start, end = min(start, 0xFFFF), min(end, 0xFFFF)  # a column past 65535 is reported at 65535
    return (((file << 32 | line) << 16 | start) << 16) | end


def unpack(loc: int) -> tuple[int, int, int, int]:
    return loc >> 64, (loc >> 32) & 0xFFFFFFFF, (loc >> 16) & 0xFFFF, loc & 0xFFFF


class Ref(NamedTuple):
    kind: str
    id: int
    path: Path
    line: int
    start: int
    end: int
    field: str


class Dup(NamedTuple):
    kind: str
    id: int
    path: Path
    line: int
    start: int
    end: int
    first_path: Path
    first_line: int


@functools.cache
def _wanted(key: str) -> frozenset[str]:
    names = {f for _, f in definers().get(key, ())}
    for card in walk_cards(layout(key)["cards"]):
        if card["kind"] == "series" and ("link" in card or "link_by" in card):
            names.add(card["name"])
        for f in card.get("fields", []):
            if "link" in f or "link_by" in f:
                names.add(f["name"])
                if "link_by" in f:
                    names.add(f["link_by"])
    return frozenset(names)


@functools.cache
def _link_kinds(key: str) -> frozenset[str]:
    out = set()
    for card in walk_cards(layout(key)["cards"]):
        for spec in [card] + card.get("fields", []):
            if "link" in spec:
                out.add(spec["link"])
            out.update(spec.get("link_map", {}).values())
    return frozenset(out)


def _long_deck(tree: Tree) -> bool:
    main = tree.files[0].source
    for block in main.blocks:
        if block.name == "KEYWORD":
            line = main.path.read_bytes().decode("latin-1").split("\n")[block.line - 1]
            return LONG_KEYWORD and "LONG=Y" in line.upper().replace(" ", "")
    return False


def _file_offsets(tree: Tree, fi: int) -> dict[str, int] | None:
    """The file's own transform offsets; None when an ancestor's apply too (composition not refereed)."""
    chain, i = [], fi
    while i is not None:
        if any(tree.files[i].offsets.values()):
            chain.append(i)
        i = tree.files[i].parent
    if not chain:
        return {}
    return tree.files[fi].offsets if chain == [fi] else None


def _shift(kind: str, offs: dict[str, int] | None) -> int | None:
    if offs is None:
        return None
    if not any(offs.values()):
        return 0
    return offs.get(OFFSET_FIELD[kind], 0) if kind in OFFSET_FIELD else None


@dataclass
class Index:
    tree: Tree
    defs: dict[str, dict[int, int]] = field(default_factory=dict)
    dups: list[tuple[str, int, int, int]] = field(default_factory=list)
    refs: dict[str, tuple[array, array, array, array]] = field(default_factory=dict)  # ids, files, locs, names
    possible: dict[str, set[int]] = field(default_factory=dict)
    uncertain_defs: dict[str, set[str]] = field(default_factory=dict)
    uncertain_uses: dict[str, set[str]] = field(default_factory=dict)
    blind: set[str] = field(default_factory=set)
    problems: list[tuple[int, FieldProblem]] = field(default_factory=list)
    unchecked: list[tuple[str, int, int, str]] = field(default_factory=list)  # kind, id, packed loc, "KEY.field"
    failures: list[tuple[int, int, str]] = field(default_factory=list)        # file index, block line, what failed
    names: list[str] = field(default_factory=list)
    _name_ids: dict[str, int] = field(default_factory=dict)

    def where(self, loc: int) -> tuple[Path, int, int, int]:
        f, line, start, end = unpack(loc)
        return self.tree.files[f].path, line, start, end

    def _at(self, fi: int, line: int) -> str:
        return f"{self.tree.files[fi].path.name}:{line}"

    def checked(self, kind: str) -> bool:
        return not self.blind and not any(k in self.uncertain_defs for k in LOOKUP.get(kind, (kind,)))

    def dangling(self) -> list[Ref]:
        out = []
        for kind, (ids, files, locs, names) in self.refs.items():
            if not self.checked(kind):
                continue
            targets = [self.defs.get(k, {}) for k in LOOKUP.get(kind, (kind,))]
            for i, id_ in enumerate(ids):
                if not any(id_ in t for t in targets):
                    out.append(Ref(kind, id_, *self.where(files[i] << 64 | locs[i]), self.names[names[i]]))
        return sorted(out, key=lambda r: (str(r.path), r.line, r.start))

    def ignored(self) -> list[Ref]:
        """References LS-DYNA accepts without checking (link_when "unchecked") whose target is not defined (DC006)."""
        out = []
        for kind, id_, loc, name in self.unchecked:
            if self.checked(kind) and not any(id_ in self.defs.get(k, {}) for k in LOOKUP.get(kind, (kind,))):
                out.append(Ref(kind, id_, *self.where(loc), name))
        return sorted(out, key=lambda r: (str(r.path), r.line, r.start))

    def duplicates(self) -> list[Dup]:
        return [Dup(kind, id_, *self.where(loc), *self.where(first)[:2]) for kind, id_, loc, first in self.dups]

    def used(self, kind: str) -> set[int]:
        out: set[int] = set()
        for k, (ids, *_) in self.refs.items():
            if kind in LOOKUP.get(k, (k,)):
                out.update(ids)
        for k, ids in self.possible.items():
            if kind in LOOKUP.get(k, (k,)):
                out.update(ids)
        return out

    def _uncertain(self, table: dict, kind: str, why: str) -> None:
        table.setdefault(kind, set()).add(why)

    def _define(self, kind: str, f: Field, fi: int, offs) -> None:
        if f.value is UNKNOWN:
            self._uncertain(self.uncertain_defs, kind, f"{self._at(fi, f.line)}: id not known")
            return
        if f.value is None or f.value == 0:
            return
        if not isinstance(f.value, int):  # a str or non-integral float: not an id deckcheck can match
            self._uncertain(self.uncertain_defs, kind, f"{self._at(fi, f.line)}: id not an integer")
            return
        if f.value < 0:
            return
        shift = _shift(kind, offs)
        if shift is None:
            self._uncertain(self.uncertain_defs, kind, "transform offset not refereed")
            return
        id_, loc = f.value + shift, pack(fi, f.line, f.start, f.end)
        if id_ > ID_MAX:
            self._uncertain(self.uncertain_defs, kind, f"{self._at(fi, f.line)}: id out of range")
            return
        seen = self.defs.setdefault(kind, {})
        if id_ in seen:
            self.dups.append((kind, id_, loc, seen[id_]))
        else:
            seen[id_] = loc

    def _reference(self, f: Field, row: dict[str, Field], fi: int, offs, key: str) -> None:
        spec, v = f.spec, f.value
        if "link_by" in spec:
            t = row.get(spec["link_by"])
            ok = t is not None and isinstance(t.value, (int, str))  # a type number, or a row name (SET_*_GENERAL)
            kind = spec["link_map"].get(str(t.value).strip().upper()) if ok else None
            if kind is None and v is not None and v != 0:  # a type deckcheck doesn't map: a use it can't place
                for k in set(spec["link_map"].values()):
                    self._uncertain(self.uncertain_uses, k, f"{self._at(fi, f.line)}: {spec['link_by']} not mapped")
                return
        else:
            kind = spec.get("link")
        if kind is None or v is None or v == 0:
            return
        if v is UNKNOWN:
            self._uncertain(self.uncertain_uses, kind, f"{self._at(fi, f.line)}: reference not known")
            return
        if isinstance(v, float) and v.is_integer():  # an id in a float field (airbag cn)
            v = int(v)
        if not isinstance(v, int) or abs(v) > ID_MAX:
            self._uncertain(self.uncertain_uses, kind, f"{self._at(fi, f.line)}: reference not an id")
            return
        shift = _shift(kind, offs)
        if shift is None:
            self._uncertain(self.uncertain_uses, kind, "transform offset not refereed")
            return
        if any(_shift(k, offs) != shift for k in LOOKUP.get(kind, (kind,))):
            # a fallback kind shifted by another offset (SET_PART -> PART): not refereed, so a use, never checked
            self.possible.setdefault(kind, set()).add(abs(v) + shift)
            return
        if spec.get("link_when") == "unchecked":  # LS-DYNA accepts a missing target here: a use, never dangling
            self.possible.setdefault(kind, set()).add(abs(v) + shift)
            self.unchecked.append((kind, abs(v) + shift, pack(fi, f.line, f.start, f.end), f"{key}.{f.name}"))
            return
        if spec.get("link_when") == "negative":
            if v > 0:
                return
            v = -v
        elif v < 0:  # a sign LS-DYNA gives a meaning deckcheck doesn't know: counts as a use, is never checked
            self.possible.setdefault(kind, set()).add(-v + shift)
            return
        name = f"{key}.{f.name}"
        if name not in self._name_ids:
            self._name_ids[name] = len(self.names)
            self.names.append(name)
        # the file index lives in its own array: pack() puts it above bit 64, past what array("q") holds
        ids, files, locs, names = self.refs.setdefault(kind, (array("q"), array("H"), array("q"), array("H")))
        ids.append(v + shift)
        files.append(fi)
        locs.append(pack(0, f.line, f.start, f.end))
        names.append(self._name_ids[name])


def build(tree: Tree) -> Index:
    ix = Index(tree)
    for p in tree.problems:
        if p.kind in ("unfollowed", "unread"):
            ix.blind.add(f"{p.file.name}:{p.line} {p.kind} *{p.name}")
    params = collect(tree)
    long_deck = _long_deck(tree)
    for fi, node in enumerate(tree.files):
        offs = _file_offsets(tree, fi)
        for block in node.source.blocks:
            name = block.name
            if name.startswith("INCLUDE_TRANSFORM"):  # its tranid is a use deckcheck doesn't record
                ix._uncertain(ix.uncertain_uses, "DEFINE_TRANSFORMATION", f"*{name} tranid not read")
                if long_deck:  # includes._offsets reads 10-wide fields
                    ix.blind.add(f"{node.path.name}:{block.line} *{name} offsets in a LONG=Y deck not read")
            if name in STRUCTURAL or name.startswith(("INCLUDE", "PARAMETER")):
                continue
            key = block.resolved.name if block.resolved else None
            if key and key.startswith("DEFINE_TABLE"):  # its curves follow it by position (torture table_before)
                ix._uncertain(ix.uncertain_uses, "DEFINE_CURVE", f"*{name}: curves taken by position")
            kinds = definers().get(key, ()) if key else ()
            fam = family_kind(key or name)
            if fam and not any(k == fam for k, _ in kinds) and not not_definer(key or name):
                ix._uncertain(ix.uncertain_defs, fam, f"*{name} defines {fam}s deckcheck can't read")
            if key is None or not _wanted(key):
                continue
            problems: list[FieldProblem] = []
            try:
                fields = read_fields(block, params, long_deck, _wanted(key), problems)
                for _, group in itertools.groupby(fields, key=attrgetter("group")):
                    row = list(group)
                    by = {f.name: f for f in row}
                    for f in row:
                        for kind, idf in kinds:
                            if f.name == idf:
                                ix._define(kind, f, fi, offs)
                        ix._reference(f, by, fi, offs, key)
            except Exception as e:  # a reader bug must not stop the run (spec §6): record it, don't trust the block
                ix.failures.append((fi, block.line, f"*{name}: {type(e).__name__}: {e}"))
                for kind, _ in kinds:
                    ix._uncertain(ix.uncertain_defs, kind, f"{ix._at(fi, block.line)} *{name} failed")
                for kind in _link_kinds(key):
                    ix._uncertain(ix.uncertain_uses, kind, f"{ix._at(fi, block.line)} *{name} failed")
                continue
            for p in problems:
                ix.problems.append((fi, p))
                if p.kind == "unread":
                    for kind, _ in kinds:
                        ix._uncertain(ix.uncertain_defs, kind, f"{node.path.name}:{p.line} unread")
                    for kind in _link_kinds(key):
                        ix._uncertain(ix.uncertain_uses, kind, f"{node.path.name}:{p.line} unread")
    return ix
