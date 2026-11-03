# M2c Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hover, go to definition, find references, outline, field hints and an "Insert field ruler" action in
VS Code, across a model's include files, without making the editor slower.

**Architecture:** a check already builds the model's index and keeps its parsed files while any of its files is open.
M2c keeps a compact copy of the index after each check (`NavIndex`: flat arrays, no Python object per id) and
answers every request from that copy and the kept parse, re-reading only the one keyword block under the cursor.
Nothing waits for a check; a file edited since its last check gets no answer until the next one.

**Tech Stack:** Python 3.11+, pygls 2.1.1 / lsprotocol, pytest + pytest-lsp, TypeScript client
(vscode-languageclient), `@vscode/test-electron`.

**Spec:** `docs/specs/2026-10-30-m2-vscode-design.md` (§3 do no harm, §5.2–5.6 features, §10 testing, §10.1 harm
gate, §11 M2c row). Parent: `docs/specs/2026-10-27-deckcheck-design.md`.

## Decisions for Chintan (plan review)

The spec leaves these open or says something this plan changes. Each is the plan's proposal; say which to change.

| # | Proposal | Why | Cost if wrong |
|---|---|---|---|
| D1 | Features answer only from the last check. A file edited since then gets no hover, definition, hints or ruler until its model is checked again (small models: 300 ms after typing stops; big models: on save). Outline is the exception: a synced file up to 2 MB is re-read from the editor's text. | An answer from stale positions would point at the wrong line. VS Code has no "refresh" for the outline, so an outline that is empty after each keystroke would stay empty. | A big model being edited has no navigation until saved. |
| D2 | No navigation before a model's first check. A big model shows "click to check"; after the check, navigation works. | Navigation needs the check's parse and index; making either on open is the cost M2b removed. | Opening a vehicle and hovering at once shows nothing. |
| D3 | Above 10,000 keywords in one file, the outline shows one line, "Outline off: N keywords in this file (more than 10,000)", instead of the status item saying so (spec §5.5). | Where the engineer looks for the outline is where the reason belongs; no client change. | Spec wording; trivial to switch. |
| D4 | Spec §4.3's `Index.at(path, line, col)` and `Index.uses(kind, id)` are replaced by `deckcheck/navigate.py`: position lookup re-reads the block under the cursor, uses come from flat arrays. | Measured on the Yaris (2026-11-01): 3.0 M definitions and 6.3 M references. A position index would hold millions of entries; the kept dicts about 300 MB. Flat arrays: about 180 MB. | None functionally; M3 reuses `navigate.py`. |
| D5 | Hover in a keyword block whose cards are not uniform rows, more than 2,000 cards below its keyword line, shows nothing. Uniform rows (`*NODE`, `*ELEMENT_SHELL`, `*ELEMENT_SOLID`, `*PART`) are read from the cursor's row alone, at any depth. | Reading a 1.5 M-card block from its start for each hover would take seconds. | Hover deep in a long `*SET_NODE_LIST`. |
| D6 | Find references lists every placed use, uncapped. Hover on a definition gives the count and says when some uses can't be placed (a transform offset, an unmapped type, an unknown sign). | "Every use" (spec §5.4); deckcheck says what it couldn't see rather than guess. | The most-used part of a vehicle returns tens of thousands of locations (gated at 1 s, Task 9). |
| D7 | Timing gates, measured on the Yaris after its check: hover and definition under 100 ms; references to the most-used part under 1 s; outline of a 10,000-keyword file under 1 s (under 50 ms repeated); hints for a screen under 100 ms anywhere in the 1.5 M-node block. Server memory after the check is reported against M2b and must stay under `memoryMB`. | The spec says "harm gate re-run with the features on" and names no numbers. | Numbers too loose or too tight; easy to revise from the measurements. |
| D8 | The ruler is offered only on fixed-column cards of synced files: not on comma-separated cards, long-format cards, or files above `maxSyncMB`. | A free-format card has no columns to name; an unsynced file's line endings aren't known. | No ruler in long-format decks. |

## Global Constraints

- deckcheck never takes part in drawing text: no syntax grammar, no semantic tokens, no decorations (spec §3).
- "No request waits for a check. Hover, definition, references, outline and hints answer from the last index or
  return nothing." (spec §3)
- Hover: "Structure and resolved references only; no descriptions" (spec §2). Never copy text from the keyword
  manual or pydyna's help strings.
- Inlay hints: hidden by default, `editor.inlayHints.enabled: offUnlessPressed` for `[keyword-deck]` (already in
  `package.json`), "Computed for the visible range only, at most 2,000 per request" (spec §5.6).
- Outline: "Above 10,000 blocks in one file, no outline is returned" (spec §5.5; D3 for how it says so).
- Core changes test-first; the CLI's output unchanged byte for byte (spec §4.3); the whole suite green after every
  task: `.venv/Scripts/python -m pytest`.
- Columns: M1 columns count characters of the text M1 read (Latin-1 from disk, editor text when synced); LSP
  positions count UTF-16 units of the text VS Code shows. Convert both ways through `lsp/convert.py`.
- Everything that builds or frees a big structure runs in the worker thread, a chunk at a time (`workspace.CHUNK`).
- Stress decks are generated locally, never committed, each run under the 2 GB lab cap. External decks are never
  committed; results hold names, counts, ids and line numbers only. A harm-gate run is the only thing running.
- Branch `m2c` from `main`. No merge, push or publish without Chintan's explicit yes. Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Code edits with the Edit tool, not shell heredocs.

## Review Focus

1. **A request while the worker drains or replaces a parse** (an edit lands, a model closes): the request must
   return nothing, never raise or read a half-emptied file. Pinned by `test_request_during_a_drain_returns_nothing`
   (Task 4).
2. **Non-ASCII text before the cursor** (a Latin-1 title in a file from disk, an editor-synced UTF-8 one): the
   field under the cursor and every returned range must be the ones the engineer sees. Pinned by
   `test_hover_after_non_ascii_text` and `test_definition_range_in_a_latin1_file` (Tasks 4, 5).
3. **A file in two models**: definition and references union both models, without duplicate locations. Pinned by
   `test_references_from_a_file_in_two_models` (Task 5).
4. **Ids shifted by `*INCLUDE_TRANSFORM`**: hover, definition and references use the shifted id; an id under an
   offset deckcheck doesn't referee gives "not resolved", never a wrong target. Pinned by
   `test_transform_definition_and_uses` (Task 2) and `test_hover_in_a_transformed_file` (Task 3).
5. **Hostile files** (1 MB single line, binary renamed `.k`, NUL bytes): every feature returns within its limit and
   the server survives. Pinned by `test_features_on_hostile_files` (Task 9).

---

## File structure

| File | Responsibility |
|---|---|
| `src/deckcheck/index.py` (modify) | `target()`: where a reference field points, pure, shared by the index and navigation; `Index.params`, `Index.long_deck` kept from `build()` |
| `src/deckcheck/navigate.py` (create) | `NavIndex` (flat tables of definitions and references, built in chunks), lookups by id, position reading (`block_at`, `card_at`, `fields_between`, `hit`, `subject`), the hover text, outline entries, ruler text. No LSP types: M3 reuses it. |
| `src/deckcheck/lsp/convert.py` (modify) | `m1_column()`: the inverse of `utf16_column()` |
| `src/deckcheck/lsp/workspace.py` (modify) | `reading` lock around drains; `parsed(main, path)`; `release_closed()` returns the released models |
| `src/deckcheck/lsp/features.py` (create) | LSP handlers' bodies: views of a file, conversion of navigate results to LSP types |
| `src/deckcheck/lsp/server.py` (modify) | keep `NavIndex` per model, forget it on release, register the features, inlay refresh after a check |
| `tests/test_navigate.py` (create) | core tests for Tasks 1–3 and 6–7 |
| `tests/test_lsp_features.py` (create) | protocol tests through pytest-lsp |
| `tests/test_lsp_stress.py` (modify) | feature timings on generated and corpus models |
| `editors/vscode/test/integration/suite.ts` (modify) | one VS Code test of hover and definition; harm-gate additions |
| `docs/m2c-navigation.md` (create), `docs/manual/README.md`, `docs/roadmap.md`, `README.md`, `docs/backlog.md`, spec status line (modify) | report and user docs |

Shared test fixture, used by Tasks 2–7 (put it at the top of `tests/test_navigate.py`; `tests/test_lsp_features.py`
imports it with `from tests.test_navigate import model`):

```python
import os
from pathlib import Path

from deckcheck.includes import resolve_tree
from deckcheck.index import build


def i10(*vals):
    return "".join(f"{v:>10}" for v in vals)


def i8(*vals):
    return "".join(f"{v:>8}" for v in vals)


NODES = "".join(i8(n) + f"{0.0:>16}" * 3 + "\n" for n in (1, 2, 3, 4))
# main.k lines: 1 *KEYWORD, 2 *INCLUDE, 3 mat.k, 4 *PART, 5 plate, 6 part card, 7 *SECTION_SHELL, 8-9 its cards,
# 10 *NODE, 11-14 nodes, 15 *ELEMENT_SHELL, 16 element, 17 *END. mat.k: 1 *KEYWORD, 2 *MAT_ELASTIC, 3 its card.
MAIN = ("*KEYWORD\n*INCLUDE\nmat.k\n*PART\nplate\n" + i10(1, 1, 1) + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n"
        + i10(1.0, 1.0, 1.0, 1.0) + "\n*NODE\n" + NODES + "*ELEMENT_SHELL\n" + i8(1, 1, 1, 2, 3, 4) + "\n*END\n")
MAT = "*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"


def model(tmp_path, main=MAIN, files=None):
    (tmp_path / "main.k").write_bytes(main.encode("latin-1"))
    for rel, text in ({"mat.k": MAT} if files is None else files).items():
        (tmp_path / rel).write_bytes(text.encode("latin-1"))
    return Path(os.path.abspath(tmp_path / "main.k"))


def nav_of(main):
    from deckcheck.navigate import build_nav
    return build_nav(build(resolve_tree(main)))
```

Columns in the fixture (0-based, `[start, end)`): part card line 6: pid `[9,10)`, secid `[19,20)`, mid `[29,30)`;
element line 16: eid `[7,8)`, pid `[15,16)`, n1 `[23,24)`, n2 `[31,32)`, n3 `[39,40)`, n4 `[47,48)`; mat.k line 3:
mid `[9,10)`.

---

### Task 1: `target()` — where a reference points, one definition for index and navigation

**Files:**
- Modify: `src/deckcheck/index.py:217-258` (`Index._reference`), `:130-145` (fields), `:286-292` (`build`)
- Test: `tests/test_navigate.py`

**Interfaces:**
- Produces: `index.Target(kind: str | None, id: int | None, how: str)` with `how` one of `"none"` (blank, 0, no
  link, or a positive value where only a negative one links), `"unmapped"`, `"unknown"`, `"not an id"`,
  `"offset"` (transform offset not refereed), `"possible"` (a use deckcheck doesn't check), `"unchecked"`
  (LS-DYNA accepts a missing target: DC006), `"checked"`.
- Produces: `index.target(f: Field, row: dict[str, Field], offs: dict[str, int] | None) -> Target`.
- Produces: `Index.params: dict`, `Index.long_deck: bool`, set by `build()`.

- [ ] **Step 0: Branch and baseline.** `git checkout main && git checkout -b m2c`. Run
  `.venv/Scripts/python -m pytest -q > %TEMP%/m2c_base.txt` and note the pass count. Time the Yaris check once with
  the scratch script from 2026-11-01 (check under the 2 GB watchdog): Expected about 64 s.

- [ ] **Step 1: Write the failing tests**

```python
from deckcheck.conditions import UNKNOWN
from deckcheck.fields import Field
from deckcheck.index import Target, target


def fld(name, value, **spec):
    return Field(name, 1, 0, 1, value, 1, {"name": name, **spec})


def test_target_plain_link():
    assert target(fld("mid", 7, link="MAT"), {}, {}) == Target("MAT", 7, "checked")


def test_target_blank_zero_and_no_link():
    assert target(fld("mid", None, link="MAT"), {}, {}).how == "none"
    assert target(fld("mid", 0, link="MAT"), {}, {}).how == "none"
    assert target(fld("ro", 1.0), {}, {}).how == "none"


def test_target_shifted_by_the_files_offset():
    assert target(fld("mid", 7, link="MAT"), {}, {"idmoff": 1000}) == Target("MAT", 1007, "checked")


def test_target_offset_not_refereed():
    assert target(fld("lcid", 7, link="DEFINE_TRANSFORMATION"), {}, {"idnoff": 5}).how == "offset"
    assert target(fld("mid", 7, link="MAT"), {}, None).how == "offset"


def test_target_unknown_and_not_an_id():
    assert target(fld("mid", UNKNOWN, link="MAT"), {}, {}).how == "unknown"
    assert target(fld("mid", "abc", link="MAT"), {}, {}).how == "not an id"


def test_target_link_by_mapped_and_unmapped():
    spec = {"link_by": "styp", "link_map": {"1": "SET_SEGMENT", "3": "PART"}}
    styp = Field("styp", 1, 10, 11, 3, 1, {"name": "styp"})
    assert target(fld("ssid", 5, **spec), {"styp": styp}, {}) == Target("PART", 5, "checked")
    odd = styp._replace(value=9)
    assert target(fld("ssid", 5, **spec), {"styp": odd}, {}).how == "unmapped"


def test_target_unchecked_negative_and_unknown_sign():
    assert target(fld("nsid", 9, link="SET_NODE", link_when="unchecked"), {}, {}) == Target("SET_NODE", 9, "unchecked")
    assert target(fld("lc", -4, link="DEFINE_CURVE", link_when="negative"), {}, {}) == Target("DEFINE_CURVE", 4, "checked")
    assert target(fld("lc", 4, link="DEFINE_CURVE", link_when="negative"), {}, {}).how == "none"
    assert target(fld("mid", -4, link="MAT"), {}, {}) == Target("MAT", 4, "possible")


def test_target_fallback_kind_under_another_offset():
    # SET_PART falls back to PART; under idsoff without idpoff the two shift differently: a use, never checked
    assert target(fld("psid", 5, link="SET_PART"), {}, {"idsoff": 10}) == Target("SET_PART", 15, "possible")


PARAM = "*KEYWORD\n*PARAMETER\n" + f"{'I m':<10}{1:>10}" + "\n"   # adds two lines: the part card moves to line 8


def test_build_keeps_params_and_long_deck(tmp_path):
    ix = build(resolve_tree(model(tmp_path, MAIN.replace("*KEYWORD\n", PARAM, 1))))
    assert ix.params == {"M": 1} and ix.long_deck is False
```

- [ ] **Step 2: Run them.** `.venv/Scripts/python -m pytest tests/test_navigate.py -q`. Expected: FAIL,
  `ImportError: cannot import name 'Target'`. (If `*PARAMETER` stores the name differently, read
  `deckcheck/params.py:26` and fix the test's expected dict, not the code.)

- [ ] **Step 3: Implement.** In `index.py`, after `_shift`:

```python
class Target(NamedTuple):
    kind: str | None
    id: int | None
    how: str  # none, unmapped, unknown, not an id, offset, possible, unchecked, checked


def target(f: Field, row: dict[str, Field], offs: dict[str, int] | None) -> Target:
    """Where a reference field points, by the rules LS-DYNA was asked about (the branches of Index._reference)."""
    spec, v = f.spec, f.value
    if "link_by" in spec:
        t = row.get(spec["link_by"])
        ok = t is not None and isinstance(t.value, (int, str))  # a type number, or a row name (SET_*_GENERAL)
        kind = spec["link_map"].get(str(t.value).strip().upper()) if ok else None
        if kind is None and v is not None and v != 0:  # a type deckcheck doesn't map: a use it can't place
            return Target(None, None, "unmapped")
    else:
        kind = spec.get("link")
    if kind is None or v is None or v == 0:
        return Target(kind, None, "none")
    if v is UNKNOWN:
        return Target(kind, None, "unknown")
    if isinstance(v, float) and v.is_integer():  # an id in a float field (airbag cn)
        v = int(v)
    if not isinstance(v, int) or abs(v) > ID_MAX:
        return Target(kind, None, "not an id")
    shift = _shift(kind, offs)
    if shift is None:
        return Target(kind, None, "offset")
    if any(_shift(k, offs) != shift for k in LOOKUP.get(kind, (kind,))):
        # a fallback kind shifted by another offset (SET_PART -> PART): not refereed, so a use, never checked
        return Target(kind, abs(v) + shift, "possible")
    if spec.get("link_when") == "unchecked":  # LS-DYNA accepts a missing target here: a use, never dangling
        return Target(kind, abs(v) + shift, "unchecked")
    if spec.get("link_when") == "negative":
        if v > 0:
            return Target(kind, None, "none")
        v = -v
    elif v < 0:  # a sign LS-DYNA gives a meaning deckcheck doesn't know: counts as a use, is never checked
        return Target(kind, -v + shift, "possible")
    return Target(kind, v + shift, "checked")
```

Replace the body of `Index._reference` with:

```python
    def _reference(self, f: Field, row: dict[str, Field], fi: int, offs, key: str) -> None:
        t = target(f, row, offs)
        if t.how in ("none", "checked", "possible", "unchecked"):
            if t.how == "checked":
                self._record(t.kind, t.id, fi, f.start, f.end, f.line, f"{key}.{f.name}")
            elif t.how == "possible":
                self.possible.setdefault(t.kind, set()).add(t.id)
            elif t.how == "unchecked":
                self.possible.setdefault(t.kind, set()).add(t.id)
                self.unchecked.append((t.kind, t.id, pack(fi, f.line, f.start, f.end), f"{key}.{f.name}"))
            return
        where = self._at(fi, f.line)  # only for the rare uncertain cases: an f-string per reference costs seconds
        if t.how == "unmapped":
            for k in set(f.spec["link_map"].values()):
                self._uncertain(self.uncertain_uses, k, f"{where}: {f.spec['link_by']} not mapped")
        elif t.how == "offset":
            self._uncertain(self.uncertain_uses, t.kind, "transform offset not refereed")
        else:
            self._uncertain(self.uncertain_uses, t.kind,
                            f"{where}: reference not known" if t.how == "unknown" else f"{where}: reference not an id")
```

Add `params: dict = field(default_factory=dict)` and `long_deck: bool = False` to `Index`, and in `build()` set
`ix.params, ix.long_deck = params, long_deck` right after they are computed.

- [ ] **Step 4: Run.** `.venv/Scripts/python -m pytest tests/test_navigate.py -q` → PASS. Then the whole suite →
  the baseline count plus the new tests, no failures. The torture parity tests (`test_cli.py`, `test_rules.py`,
  `test_index.py` and the LSP parity test) are what prove the refactor changed nothing.

- [ ] **Step 5: Measure.** Re-time the Yaris check. Expected: within 2 % of Step 0. More than that: the
  NamedTuple per reference is the suspect; return plain tuples instead and re-measure.

- [ ] **Step 6: Commit.** `git add src/deckcheck/index.py tests/test_navigate.py` —
  "index.target(): where a reference field points, shared by the index and M2c navigation; the index keeps the
  model's parameters and LONG=Y flag".

---

### Task 2: `NavIndex` — definitions and uses by id, from flat arrays

**Files:**
- Create: `src/deckcheck/navigate.py`
- Test: `tests/test_navigate.py`

**Interfaces:**
- Consumes: `Index` (Task 1 fields), `index.LOOKUP`, `index.unpack`, `workspace.CHUNK` (import the constant
  value `CHUNK = 20_000` into `navigate.py` instead; core must not import `lsp`).
- Produces: `navigate.Loc(fi: int, path: Path, line: int, start: int, end: int)`.
- Produces: `navigate.Table` with `find(id_: int) -> Iterator[int]` and `loc(i: int, tree) -> Loc`.
- Produces: `navigate.NavIndex` with `tree`, `params`, `long_deck`, `checked(kind) -> bool`, `owner(kind, id_) -> str`,
  `definitions(kind, id_) -> list[Loc]`, `uses(kind, id_) -> list[Loc]`, `uses_complete(kind) -> list[str]`
  (reasons some uses can't be placed; empty when all are), `file_index(path) -> int | None`.
- Produces: `navigate.build_nav(ix: Index) -> NavIndex` (worker thread; after it the caller may drain `ix`).

- [ ] **Step 1: Write the failing tests**

```python
import struct
from array import array

from deckcheck.navigate import Loc, Table, build_nav
TORTURE = Path(__file__).parent / "torture"


def test_find_ignores_matches_across_two_ids():
    # 1 << 56 then 0: the bytes of id 1 appear at offset 7, inside the first two ids
    t = Table(bytearray(array("q", [1 << 56, 0, 1]).tobytes()), array("H", [0, 0, 0]), array("q", [0, 0, 0]))
    assert list(t.find(1)) == [2]


def test_definitions_and_uses_across_includes(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    mat = main.parent / "mat.k"
    assert [(l.path, l.line, l.start, l.end) for l in nav.definitions("MAT", 1)] == [(mat, 3, 9, 10)]
    assert [(l.path, l.line, l.start, l.end) for l in nav.uses("MAT", 1)] == [(main, 6, 29, 30)]
    assert [(l.line, l.start) for l in nav.uses("NODE", 3)] == [(16, 39)]
    assert nav.definitions("MAT", 2) == [] and nav.checked("MAT")


def test_a_duplicate_has_every_definition(tmp_path):
    main = model(tmp_path, files={"mat.k": MAT.replace("*END\n", "*MAT_ELASTIC\n" + i10(1, 1.0, 1.0, 0.3) + "\n*END\n")})
    assert [l.line for l in nav_of(main).definitions("MAT", 1)] == [3, 5]


def test_a_part_set_id_without_a_set_resolves_to_the_part(tmp_path):
    nav = nav_of(model(tmp_path))
    assert [l.line for l in nav.definitions("SET_PART", 1)] == [6]


def test_transform_definition_and_uses():
    case = Path(os.path.abspath(TORTURE / "inc_transform"))
    nav = nav_of(case / "main.k")
    mesh = case / "mesh.k"
    assert [(l.path, l.line, l.start) for l in nav.definitions("NODE", 101)] == [(mesh, 3, 7)]
    assert [(l.path, l.line, l.start) for l in nav.uses("NODE", 101)] == [(mesh, 8, 23)]
    assert nav.definitions("NODE", 1) == []


def test_uses_complete_names_what_it_could_not_place(tmp_path):
    nav = nav_of(model(tmp_path, MAIN.replace(i10(1, 1, 1), i10(1, 1, -1))))  # a negative mid: a possible use
    assert nav.uses_complete("MAT") != [] and nav.uses_complete("SECTION") == []
```

- [ ] **Step 2: Run.** Expected: FAIL, `ModuleNotFoundError: deckcheck.navigate`.

- [ ] **Step 3: Implement** `src/deckcheck/navigate.py`:

```python
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
```

Note on `definitions` order for a duplicate: `d.items()` holds the first definition, `ix.dups` the later ones, so
the first comes first. `test_a_duplicate_has_every_definition` pins this.

- [ ] **Step 4: Run** the new tests, then the whole suite. Expected: PASS. If `test_uses_complete...` fails because a
  negative `mid` reads differently, print `ix.possible` and pick a field whose negative value is a "possible" use
  per `test_target_unchecked_negative_and_unknown_sign`; don't change the code to fit the test.

- [ ] **Step 5: Commit** "navigate.py: NavIndex, definitions and uses by id from flat arrays (plan D4)".

---

### Task 3: Position reading and the hover text

**Files:**
- Modify: `src/deckcheck/navigate.py`
- Test: `tests/test_navigate.py`

**Interfaces:**
- Produces: `READ_LIMIT = 2000`.
- Produces: `block_at(src: SourceFile, line: int) -> Block | None` (the block whose keyword line is at or above
  `line`, if `line` is that keyword line or one of its cards' lines).
- Produces: `card_at(block: Block, line: int) -> Card | None`; `line_text(src, line) -> str | None` (a card's text or
  a keyword line's text).
- Produces: `fields_between(block, first, last, params, long_deck) -> list[Field] | None` (None: deckcheck can't
  tell, D5).
- Produces: `hit(fields: list[Field], col: int) -> Field | None` (value span; a blank field over its slot).
- Produces: `subject(nav, fi, fields, f) -> tuple[str, int, bool] | None`: `(kind, id, is_definition)` after
  offsets; None when the field neither defines nor references a resolvable id.
- Produces: `explain(nav, fi, fields, f) -> str` (Markdown); `explain_keyword(block) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
from deckcheck.navigate import READ_LIMIT, block_at, card_at, explain, explain_keyword, fields_between, hit, subject
from deckcheck.reader import read_file


def at(nav, path, line, col):
    fi = nav.file_index(path)
    block = block_at(nav.tree.files[fi].source, line)
    fields = fields_between(block, line, line, nav.params, nav.long_deck)
    return fi, fields, hit(fields, col)


def test_the_field_under_a_column(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    _, fields, f = at(nav, main, 6, 29)
    assert [x.name for x in fields][:3] == ["pid", "secid", "mid"] and f.name == "mid"
    assert at(nav, main, 16, 23)[2].name == "n1"


def test_padding_and_blank_fields(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    assert at(nav, main, 6, 25)[2] is None            # spaces before mid's value
    assert at(nav, main, 6, 35)[2].name == "eosid"    # blank: hit across its whole 10-wide slot


def test_a_row_deep_in_a_big_table_is_read_alone(tmp_path):
    nodes = "".join(i8(n) + f"{0.0:>16}" * 3 + "\n" for n in range(1, 50_001))
    main = model(tmp_path, "*KEYWORD\n*NODE\n" + nodes + "*END\n", files={})
    nav = nav_of(main)
    block = block_at(nav.tree.files[0].source, 40_002)
    fields = fields_between(block, 40_002, 40_002, nav.params, nav.long_deck)
    assert fields[0].name == "nid" and fields[0].value == 40_000 and fields[0].line == 40_002


def test_deep_in_a_non_uniform_block_says_nothing(tmp_path):
    rows = "".join(i10(n) + "\n" for n in range(1, READ_LIMIT + 1000))
    main = model(tmp_path, "*KEYWORD\n*SET_NODE_LIST\n" + i10(1) + "\n" + rows + "*END\n", files={})
    nav = nav_of(main)
    block = block_at(nav.tree.files[0].source, 5)
    assert fields_between(block, 5, 5, nav.params, nav.long_deck) is not None
    assert fields_between(block, READ_LIMIT + 500, READ_LIMIT + 500, nav.params, nav.long_deck) is None


def test_subject_of_a_reference_and_a_definition(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    fi, fields, f = at(nav, main, 6, 29)
    assert subject(nav, fi, fields, f) == ("MAT", 1, False)
    fi, fields, f = at(nav, main, 6, 9)
    assert subject(nav, fi, fields, f) == ("PART", 1, True)


def test_hover_on_a_resolved_reference(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    text = explain(nav, *at(nav, main, 6, 29))
    assert "**mid**" in text and "columns 21-30" in text and "integer" in text
    assert "mid → MAT 1, *MAT_ELASTIC at mat.k:3" in text


def test_hover_on_a_definition_counts_its_uses(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    text = explain(nav, *at(nav, main.parent / "mat.k", 3, 9))
    assert "Defines MAT 1" in text and "1 use" in text


def test_hover_on_a_dangling_and_an_ignored_reference(tmp_path):
    main = model(tmp_path, MAIN.replace(i10(1, 1, 1), i10(1, 1, 99)))
    nav = nav_of(main)
    assert "MAT 99 is not defined" in explain(nav, *at(nav, main, 6, 29))
    case = Path(os.path.abspath(TORTURE / "spc_set_none"))
    nav = nav_of(case / "main.k")
    assert "LS-DYNA accepts this, but the reference has no effect" in explain(nav, *at(nav, case / "main.k", 22, 9))


def test_hover_on_a_blank_field_gives_its_default(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    assert "blank" in explain(nav, *at(nav, main, 6, 35)) and "default: 0" in explain(nav, *at(nav, main, 6, 35))


def test_hover_value_as_read_after_a_parameter(tmp_path):
    main = model(tmp_path, MAIN.replace("*KEYWORD\n", PARAM, 1).replace(i10(1, 1, 1), i10(1, 1, "&m")))
    nav = nav_of(main)
    text = explain(nav, *at(nav, main, 8, 28))         # "&m" right-aligned in mid's slot: columns 28-29
    assert "&m = 1" in text and "MAT 1" in text


def test_hover_in_a_transformed_file():
    case = Path(os.path.abspath(TORTURE / "inc_transform"))
    nav = nav_of(case / "main.k")
    text = explain(nav, *at(nav, case / "mesh.k", 8, 23))
    assert "NODE 101" in text and "offset 100" in text and "mesh.k:3" in text


def test_hover_on_a_keyword_line(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    assert explain_keyword(block_at(nav.tree.files[0].source, 4)).startswith("*PART")
    src = read_file(tmp_path / "x.k", "*KEYWORD\n*NOT_A_KEYWORD\n1\n")
    assert "not in deckcheck's keyword data; passed through" in explain_keyword(block_at(src, 2))
```

The `spc_set_none` line and column (22, 9) come from the README's JSON example. If the torture deck differs, read
its `expected.toml` and use the DC006 finding's line and column.

- [ ] **Step 2: Run.** Expected: FAIL on the imports.

- [ ] **Step 3: Implement** (append to `navigate.py`; add the imports `bisect`, `Block`, `Card`, `SourceFile` from
  `deckcheck.reader`, `read_fields`, `is_long`, `Field` from `deckcheck.fields`, `definers` from
  `deckcheck.definers`, `layout` from `deckcheck.keywords`, `target`, `_shift`, `_file_offsets`, `_span` from
  `deckcheck.index`):

```python
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
```

- [ ] **Step 4: Run** the new tests and the suite. Expected: PASS. Measure `fields_between` at line
  `READ_LIMIT + 1` of the `SET_NODE_LIST` test with `time.perf_counter()`: Expected under 50 ms; over that,
  lower `READ_LIMIT` and note it as a ruling.

- [ ] **Step 5: Commit** "navigate.py: the field under a position (uniform rows read alone, others up to 2,000
  cards), hover text with resolved references, offsets and parameters".

---

### Task 4: Server plumbing and hover

**Files:**
- Modify: `src/deckcheck/lsp/convert.py`, `src/deckcheck/lsp/workspace.py:105-129`, `src/deckcheck/lsp/server.py`
- Create: `src/deckcheck/lsp/features.py`
- Test: `tests/test_lsp_convert.py`, `tests/test_lsp_workspace.py`, create `tests/test_lsp_features.py`

**Interfaces:**
- Consumes: `navigate.*` (Tasks 2–3).
- Produces: `convert.m1_column(line: str, character: int, from_disk: bool) -> int`.
- Produces: `Workspace.reading: threading.Lock`; `Workspace.parsed(main: Path, path: Path) -> SourceFile | None`;
  `Workspace.release_closed() -> list[str]` (released model keys).
- Produces: `DeckServer.nav: dict[str, NavIndex]`; `Result.nav: NavIndex | None`.
- Produces: `features.View(nav, fi, src, disk)`; `features.views(ls, path) -> list[View]`;
  `features.guarded(ls, fn)`; `features.hover(ls, path: Path, position: types.Position) -> types.Hover | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_lsp_convert.py`:

```python
from deckcheck.lsp.convert import m1_column, utf16_column


def test_m1_column_inverts_utf16_column():
    disk = "é é".encode("utf-8").decode("latin-1") + "   1"   # what M1 read from a UTF-8 file
    for col in range(len(disk) + 1):
        assert m1_column(disk, utf16_column(disk, col, True), True) <= col
    assert m1_column("abc", 2, False) == 2 and m1_column("ab", 9, False) == 2
```

`tests/test_lsp_workspace.py`:

```python
def test_parsed_is_none_once_a_file_changes(tmp_path):
    main = model(tmp_path)          # from tests.test_navigate
    ws = Workspace([tmp_path], Settings())
    ws.ensure_scanned()
    from deckcheck.includes import resolve_tree
    resolve_tree(main, cache=ws.cache_for(main))
    assert ws.parsed(main, main) is not None
    ws.change(main, main.read_text())
    assert ws.parsed(main, main) is None


def test_release_closed_returns_what_it_freed(tmp_path):
    main = model(tmp_path)
    ws = Workspace([tmp_path], Settings())
    ws.ensure_scanned()
    from deckcheck.includes import resolve_tree
    resolve_tree(main, cache=ws.cache_for(main))
    from deckcheck.includes import _key
    assert ws.release_closed() == [_key(main)]
```

`tests/test_lsp_features.py` (reuses `session`, `open_doc`, `published`, `uri` from `tests/test_lsp_server.py`):

```python
import asyncio
import threading

import pytest
from lsprotocol import types

from tests.test_lsp_server import open_doc, published, session, uri
from tests.test_navigate import MAIN, i10, model


def pos(line, character):
    return types.Position(line - 1, character)


async def hover(client, path, line, character):
    return await client.text_document_hover_async(types.HoverParams(
        types.TextDocumentIdentifier(uri(path)), pos(line, character)))


@pytest.mark.asyncio
async def test_hover_on_a_reference_across_includes(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        h = await hover(client, main, 6, 29)
        assert "mid → MAT 1, *MAT_ELASTIC at mat.k:3" in h.contents.value


@pytest.mark.asyncio
async def test_hover_before_a_check_and_after_an_edit_says_nothing(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path, liveThresholdSeconds=0) as client:   # a big model: never checked on open
        open_doc(client, main)
        await asyncio.sleep(1)
        assert await hover(client, main, 6, 29) is None
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri(main), 2),
            [types.TextDocumentContentChangeWholeDocument(MAIN.replace("plate", "plate2"))]))
        assert await hover(client, main, 6, 29) is None              # until the re-check
        await published(client, uri(main))
        assert await hover(client, main, 6, 29) is not None


@pytest.mark.asyncio
async def test_hover_after_non_ascii_text(tmp_path):
    # one character in pid's slot padding that is two UTF-16 units: M1 sees mid at column 29, the editor at 30
    main = model(tmp_path)
    text = MAIN.replace(i10(1, 1, 1), "\U0001F600" + i10(1, 1, 1)[1:])
    async with session(tmp_path) as client:
        open_doc(client, main, text)                                  # synced: M1 reads the editor's text
        await published(client, uri(main))
        h = await hover(client, main, 6, 30)
        assert "**mid**" in h.contents.value and h.range.start.character == 30


@pytest.mark.asyncio
async def test_request_during_a_drain_returns_nothing(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        reply = await client.protocol.send_request_async("deckcheck/testHoldReading", {"seconds": 1.0})
        assert reply["held"]
        assert await hover(client, main, 6, 29) is None
```

`deckcheck/testHoldReading` is a test-only request, registered only when `DECKCHECK_TEST_HOOKS=1` is in the
server's environment. Give `session()` in `tests/test_lsp_server.py` an `env: dict | None = None` argument passed
to `client.start_io(sys.executable, "-m", "deckcheck.lsp", env=env)`, and call it here with
`env={**os.environ, "DECKCHECK_TEST_HOOKS": "1"}`. In `server.py`:

```python
if os.environ.get("DECKCHECK_TEST_HOOKS") == "1":  # tests only: hold the lock the worker holds while freeing parses
    @server.feature("deckcheck/testHoldReading")
    def hold_reading(ls: DeckServer, params) -> dict:
        seconds = params["seconds"] if isinstance(params, dict) else params.seconds
        held = threading.Event()

        def hold():
            with ls.ws.reading:
                held.set()
                time.sleep(seconds)
        threading.Thread(target=hold, daemon=True).start()
        return {"held": held.wait(5)}
```

The two column tests split the conversions: `test_hover_after_non_ascii_text` (here) covers editor text, where
one character can be two UTF-16 units; `test_definition_range_in_a_latin1_file` (Task 5) covers a file read from
disk, where two bytes are one character on screen.

- [ ] **Step 2: Run** the four files. Expected: FAIL (`m1_column` missing; `parsed` missing; hover returns None).

- [ ] **Step 3: Implement**

`convert.py`:

```python
def m1_column(line: str, character: int, from_disk: bool) -> int:
    """The M1 column of an editor position: the first column whose UTF-16 position reaches it."""
    lo, hi = 0, len(line)
    while lo < hi:
        mid = (lo + hi) // 2
        if utf16_column(line, mid, from_disk) < character:
            lo = mid + 1
        else:
            hi = mid
    return lo
```

`workspace.py`: in `__init__`, `self.reading = threading.Lock()  # held while parses are freed; requests never
wait for it`. Wrap the draining loops of `apply_drops` and `release_closed` in `with self.reading:`.
`release_closed` collects and returns the released keys. Add:

```python
    def parsed(self, main: Path, path: Path) -> SourceFile | None:
        """The model's parse of a file, unless the file changed since (a drop not yet applied counts)."""
        k = _key(_norm(path))
        with self._lock:
            if k in self._drops:
                return None
            return self._caches.get(_key(_norm(main)), {}).get(k)
```

`features.py`:

```python
"""M2c request handlers' bodies (M2 spec §5.2-5.6): answers from the last check's index and parse, or nothing
(spec §3). A request never waits: if the worker is freeing parses, the answer is nothing."""
from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types

from deckcheck.includes import _key
from deckcheck.lsp.convert import m1_column, utf16_column
from deckcheck.navigate import NavIndex, block_at, card_at, explain, explain_keyword, fields_between, hit
from deckcheck.reader import SourceFile


@dataclass
class View:
    nav: NavIndex
    fi: int
    src: SourceFile
    disk: bool


def views(ls, path: Path) -> list[View]:
    """Each model of the file whose last check's parse of it is still the current one."""
    out = []
    for m in ls.ws.models_for(path):
        nav = ls.nav.get(_key(m))
        fi = nav.file_index(path) if nav else None
        if fi is None:
            continue
        src = nav.tree.files[fi].source
        if ls.ws.parsed(m, path) is src:
            out.append(View(nav, fi, src, not ls.ws.synced(path)))
    return out


def guarded(ls, fn):
    if not ls.ws.reading.acquire(blocking=False):
        return None
    try:
        return fn()
    except Exception as e:  # a navigation bug must never break the session (spec §3)
        ls.window_log_message(types.LogMessageParams(types.MessageType.Error, f"deckcheck: request failed: {e!r}"))
        return None
    finally:
        ls.ws.reading.release()


def hover(ls, path: Path, position: types.Position) -> types.Hover | None:
    def run():
        vs = views(ls, path)
        if not vs:
            return None
        v, line = vs[0], position.line + 1
        block = block_at(v.src, line)
        if block is None:
            return None
        if line == block.line:
            return types.Hover(types.MarkupContent(types.MarkupKind.Markdown, explain_keyword(block)))
        card = card_at(block, line)
        fields = fields_between(block, line, line, v.nav.params, v.nav.long_deck)
        if fields is None:
            return None
        f = hit(fields, m1_column(card.text, position.character, v.disk))
        text = explain(v.nav, v.fi, fields, f)
        if text is None:
            return None
        rng = types.Range(types.Position(line - 1, utf16_column(card.text, f.start, v.disk)),
                          types.Position(line - 1, utf16_column(card.text, max(f.end, f.start), v.disk)))
        return types.Hover(types.MarkupContent(types.MarkupKind.Markdown, text), range=rng)
    return guarded(ls, run)
```

`server.py`:
- `DeckServer.nav: dict[str, NavIndex]`; `initialize` sets `ls.nav = {}`.
- `Result` gets `nav: object = None`; `_check` sets `result.nav = build_nav(report.index)` before
  `drain_index(report.index)`.
- `_publish`: success → `ls.nav[k] = result.nav`; failure → `ls.nav.pop(k, None)`.
- `_prepare` and `_check`'s `finally`: `released = ls.ws.release_closed()`, then
  `ls.loop.call_soon_threadsafe(_forget, ls, released)` where `_forget` pops each key from `ls.nav`.
- Register:

```python
@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: DeckServer, params: types.HoverParams) -> types.Hover | None:
    path = _path(params.text_document.uri)
    return features.hover(ls, path, params.position) if path else None
```

- [ ] **Step 4: Run** the four test files, then the whole suite, including the parity and stress-marked tests that
  run by default. Expected: PASS.

- [ ] **Step 5: Commit** "Hover (spec §5.2): the server keeps a NavIndex per model after each check and answers from
  it and the kept parse; nothing for a file edited since or while parses are freed".

---

### Task 5: Go to definition and find references

**Files:**
- Modify: `src/deckcheck/lsp/features.py`, `src/deckcheck/lsp/server.py`
- Test: `tests/test_lsp_features.py`

**Interfaces:**
- Consumes: `View`, `views`, `guarded` (Task 4); `navigate.subject`, `NavIndex.definitions/uses`, `line_text`.
- Produces: `features.definition(ls, path, position) -> list[types.Location] | None`;
  `features.references(ls, path, position, include_declaration: bool) -> list[types.Location] | None`;
  `features.location(ls, nav, loc) -> types.Location`.

- [ ] **Step 1: Write the failing tests**

```python
async def definition(client, path, line, character):
    return await client.text_document_definition_async(types.DefinitionParams(
        types.TextDocumentIdentifier(uri(path)), pos(line, character)))


async def references(client, path, line, character, decl=False):
    return await client.text_document_references_async(types.ReferenceParams(
        context=types.ReferenceContext(include_declaration=decl),
        text_document=types.TextDocumentIdentifier(uri(path)), position=pos(line, character)))


def spans(locs):
    return sorted((l.uri, l.range.start.line + 1, l.range.start.character, l.range.end.character) for l in locs)


@pytest.mark.asyncio
async def test_definition_across_includes_and_on_itself(tmp_path):
    main = model(tmp_path)
    mat = tmp_path / "mat.k"
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert spans(await definition(client, main, 6, 29)) == [(uri(mat), 3, 9, 10)]
        assert spans(await definition(client, main, 16, 39)) == [(uri(main), 13, 7, 8)]   # n3 -> NODE 3
        assert spans(await definition(client, main, 6, 9)) == [(uri(main), 6, 9, 10)]     # PART 1 itself


@pytest.mark.asyncio
async def test_references_with_and_without_the_declaration(tmp_path):
    main = model(tmp_path)
    mat = tmp_path / "mat.k"
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert spans(await references(client, mat, 3, 9)) == [(uri(main), 6, 29, 30)]
        assert spans(await references(client, main, 6, 29, decl=True)) == [(uri(main), 6, 29, 30), (uri(mat), 3, 9, 10)]


@pytest.mark.asyncio
async def test_definition_range_in_a_latin1_file(tmp_path):
    # part.k is never opened, so M1 reads it from disk: a UTF-8 é (two bytes) in pid's padding puts mid at M1
    # column 29 and at editor column 28
    main = model(tmp_path, "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n",
                 files={"mat.k": MAT, "part.k": "*KEYWORD\n*PART\nplate\n" + "Ã©" + i10(1, 1, 1)[2:]
                        + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n*END\n"})
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k")
        await published(client, uri(tmp_path / "mat.k"))
        assert spans(await references(client, tmp_path / "mat.k", 3, 9)) == [(uri(tmp_path / "part.k"), 4, 28, 29)]


@pytest.mark.asyncio
async def test_references_from_a_file_in_two_models(tmp_path):
    model(tmp_path)
    (tmp_path / "other.k").write_bytes(b"*KEYWORD\n*INCLUDE\nmat.k\n*PART\nq\n" + i10(2, 1, 1).encode() + b"\n*END\n")
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k")
        await published(client, uri(tmp_path / "mat.k"))
        await asyncio.sleep(2)                                     # both models checked
        got = spans(await references(client, tmp_path / "mat.k", 3, 9))
        assert got == sorted({(uri(tmp_path / "main.k"), 6, 29, 30), (uri(tmp_path / "other.k"), 6, 29, 30)})
```

If `published` returns before the second model is checked, replace the sleep with a wait on two `deckcheck/status`
notifications with state `ok`, one per main deck (see `last_status` in `tests/test_lsp_server.py`).

- [ ] **Step 2: Run.** Expected: FAIL (no definition provider: the client raises "method not found" or returns None).

- [ ] **Step 3: Implement** in `features.py`:

```python
def location(ls, nav: NavIndex, loc) -> types.Location:
    text = line_text(nav.tree.files[loc.fi].source, loc.line) or ""
    disk = not ls.ws.synced(loc.path)
    return types.Location(from_fs_path(str(loc.path)), types.Range(
        types.Position(loc.line - 1, utf16_column(text, loc.start, disk)),
        types.Position(loc.line - 1, utf16_column(text, loc.end, disk))))


def _subjects(ls, path: Path, position: types.Position) -> list[tuple[View, tuple[str, int, bool]]]:
    out = []
    for v in views(ls, path):
        line = position.line + 1
        block = block_at(v.src, line)
        card = card_at(block, line) if block else None
        fields = fields_between(block, line, line, v.nav.params, v.nav.long_deck) if card else None
        f = hit(fields, m1_column(card.text, position.character, v.disk)) if fields else None
        s = subject(v.nav, v.fi, fields, f) if f else None
        if s:
            out.append((v, s))
    return out


def _unique(locations: list[types.Location]) -> list[types.Location]:
    seen, out = set(), []
    for l in locations:
        k = (l.uri, l.range.start.line, l.range.start.character)
        if k not in seen:
            seen.add(k)
            out.append(l)
    return out


def definition(ls, path: Path, position: types.Position) -> list[types.Location] | None:
    def run():
        found = [location(ls, v.nav, l) for v, (kind, id_, _) in _subjects(ls, path, position)
                 for l in v.nav.definitions(kind, id_)]
        return _unique(found) or None
    return guarded(ls, run)


def references(ls, path: Path, position: types.Position, include_declaration: bool) -> list[types.Location] | None:
    def run():
        found = []
        for v, (kind, id_, is_def) in _subjects(ls, path, position):
            # a reference's uses are the uses of the definition it resolves to (a part set id may mean the part)
            target = kind if is_def else v.nav.owner(kind, id_)
            found += [location(ls, v.nav, l) for l in v.nav.uses(target, id_)]
            if include_declaration:
                found += [location(ls, v.nav, l) for l in v.nav.definitions(target, id_)]
        return _unique(found) or None
    return guarded(ls, run)
```

(imports: `from pygls.uris import from_fs_path`, `line_text`, `subject`.)
Register `TEXT_DOCUMENT_DEFINITION` and `TEXT_DOCUMENT_REFERENCES` in `server.py` the way `hover` is.

- [ ] **Step 4: Run** the tests, then the suite. Expected: PASS.

- [ ] **Step 5: Commit** "Go to definition and find references (spec §5.3-5.4), across include files and models,
  ids shifted by *INCLUDE_TRANSFORM".

---

### Task 6: Outline

**Files:**
- Modify: `src/deckcheck/navigate.py`, `src/deckcheck/lsp/features.py`, `src/deckcheck/lsp/server.py`
- Test: `tests/test_navigate.py`, `tests/test_lsp_features.py`

**Interfaces:**
- Produces: `navigate.MAX_OUTLINE = 10_000`; `navigate.Entry(name: str, detail: str, line: int, end_line: int)`;
  `navigate.outline(src, params, long_deck) -> list[Entry] | int` (an int: the block count, over the cap).
- Produces: `features.outline(ls, path) -> list[types.DocumentSymbol]`; `features.OUTLINE_REPARSE_MB = 2`.

- [ ] **Step 1: Write the failing tests**

```python
from deckcheck.navigate import MAX_OUTLINE, outline


def test_outline_names_keyword_id_and_title(tmp_path):
    mat = MAT.replace("*MAT_ELASTIC\n", "*MAT_ELASTIC_TITLE\nsteel\n")
    main = model(tmp_path, files={"mat.k": mat})
    nav = nav_of(main)
    names = [e.name for e in outline(nav.tree.files[0].source, nav.params, nav.long_deck)]
    assert names[:5] == ["*INCLUDE", "*PART 1 plate", "*SECTION_SHELL 1", "*NODE", "*ELEMENT_SHELL 1"]
    assert [e.name for e in outline(nav.tree.files[1].source, {}, False)] == ["*MAT_ELASTIC_TITLE 1 steel"]


def test_outline_of_a_block_defining_many_says_how_many_cards(tmp_path):
    nav = nav_of(model(tmp_path))
    node = outline(nav.tree.files[0].source, nav.params, nav.long_deck)[3]
    assert node.name == "*NODE" and node.detail == "4 cards" and (node.line, node.end_line) == (10, 14)


def test_outline_over_the_cap_returns_the_count(tmp_path):
    body = "*KEYWORD\n" + ("*DEFINE_CURVE\n" + i10(1) + "\n") * (MAX_OUTLINE + 1) + "*END\n"
    src = read_file(tmp_path / "big.k", body)
    assert outline(src, {}, False) == MAX_OUTLINE + 2      # *KEYWORD is a block too; *END ends the reading
    at_cap = "*KEYWORD\n" + ("*DEFINE_CURVE\n" + i10(1) + "\n") * (MAX_OUTLINE - 1) + "*END\n"
    assert len(outline(read_file(tmp_path / "ok.k", at_cap), {}, False)) == MAX_OUTLINE
```

Protocol test (in `tests/test_lsp_features.py`):

```python
async def symbols(client, path):
    return await client.text_document_document_symbol_async(types.DocumentSymbolParams(
        types.TextDocumentIdentifier(uri(path))))


@pytest.mark.asyncio
async def test_outline_follows_unsaved_text_of_a_small_file(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert (await symbols(client, main))[1].name == "*PART 1 plate"
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri(main), 2),
            [types.TextDocumentContentChangeWholeDocument(MAIN.replace("plate", "door"))]))
        assert (await symbols(client, main))[1].name == "*PART 1 door"          # before the re-check (D1)


@pytest.mark.asyncio
async def test_outline_off_says_why(tmp_path):
    body = "*KEYWORD\n" + ("*DEFINE_CURVE\n" + i10(1) + "\n") * (MAX_OUTLINE + 1) + "*END\n"
    (tmp_path / "main.k").write_text(body)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await published(client, uri(tmp_path / "main.k"))
        got = await symbols(client, tmp_path / "main.k")
        assert len(got) == 1 and got[0].name.startswith("Outline off: 10,002 keywords")
```

- [ ] **Step 2: Run.** Expected: FAIL on the imports.

- [ ] **Step 3: Implement** in `navigate.py`:

```python
MAX_OUTLINE = 10_000  # spec §5.5: above this, no outline, so the panel can't stall
TITLE_FIELDS = ("title", "heading")


class Entry(NamedTuple):
    name: str
    detail: str
    line: int
    end_line: int


def _label(block: Block, params: dict, long_deck: bool) -> tuple[str, str]:
    name, detail = f"*{block.name}", ""
    if block.resolved is None:
        return name, "not in deckcheck's keyword data"
    idf = next((f for _, f in definers().get(block.resolved.name, ())), None)
    ids, title = [], None
    for f in read_fields(block, params, long_deck, frozenset({idf, *TITLE_FIELDS} - {None})):
        if f.name == idf:
            ids.append(f.value)
            if len(ids) > 1:
                break
        elif title is None and isinstance(f.value, str):
            title = f.value
    if len(ids) == 1 and ids[0] is not None:
        name += f" {ids[0]}" + (f" {title}" if title else "")
    elif len(ids) > 1 or not idf:
        detail = _plural(len(block.cards), "card")
    return name, detail


def outline(src: SourceFile, params: dict, long_deck: bool) -> list[Entry] | int:
    if len(src.blocks) > MAX_OUTLINE:
        return len(src.blocks)
    out = []
    for b in src.blocks:
        name, detail = _label(b, params, long_deck)
        out.append(Entry(name, detail, b.line, b.cards[-1].line if b.cards else b.line))
    return out
```

`*INCLUDE` has no definer field, so it gets `detail` "1 card"; the first test asserts names only. `*MAT_ELASTIC_TITLE`:
the title card is read first (pre option), the id after it; the loop keeps both.

`features.py`:

```python
OUTLINE_REPARSE_MB = 2  # a synced file this small is re-read from the editor's text for the outline (D1)


def outline(ls, path: Path) -> list[types.DocumentSymbol]:
    def run():
        vs = views(ls, path)
        if vs:
            src, nav, disk = vs[0].src, vs[0].nav, vs[0].disk
        else:
            text = ls.ws.source(path)
            if text is None or len(text) > OUTLINE_REPARSE_MB * 2**20:
                return []
            navs = [ls.nav[_key(m)] for m in ls.ws.models_for(path) if _key(m) in ls.nav]
            nav = navs[0] if navs else None
            src, disk = read_file(path, text), False
        got = outline_entries(src, nav.params if nav else {}, nav.long_deck if nav else False)
        if isinstance(got, int):
            r = types.Range(types.Position(0, 0), types.Position(0, 0))
            return [types.DocumentSymbol(f"Outline off: {got:,} keywords in this file (more than {MAX_OUTLINE:,})",
                                         types.SymbolKind.Null, r, r)]
        out = []
        for e in got:
            end_text = line_text(src, e.end_line) or ""
            r = types.Range(types.Position(e.line - 1, 0),
                            types.Position(e.end_line - 1, utf16_column(end_text, len(end_text), disk)))
            sel = types.Range(types.Position(e.line - 1, 0), types.Position(e.line - 1, 0))
            out.append(types.DocumentSymbol(e.name, types.SymbolKind.Struct, r, sel, detail=e.detail or None))
        return out
    return guarded(ls, run) or []
```

(import `outline as outline_entries`, `MAX_OUTLINE`, `line_text` from navigate and `read_file` from reader.)

Cache the answer for a kept parse: a 4,000-block include is labelled once, not on every request. Add
`ls.outlines: dict[str, tuple[SourceFile, list]] = {}` in `initialize`, and in `run()`:

```python
        if vs:
            hit_ = ls.outlines.get(_key(path))
            if hit_ is not None and hit_[0] is vs[0].src:
                return hit_[1]
        # ... compute `out` as above ...
        if vs:
            ls.outlines[_key(path)] = (vs[0].src, out)
        return out
```

A re-read from the editor's text is a new object each time and is not cached. `_forget` (Task 4) also pops
`ls.outlines` entries of the released models' files. Register `TEXT_DOCUMENT_DOCUMENT_SYMBOL`.

- [ ] **Step 4: Run** the tests and the suite. Time `outline` on the 10,000-block file: Expected under 1 s. Over that,
  report the number and stop for a ruling (the cap stays the spec's).

- [ ] **Step 5: Commit** "Outline (spec §5.5): one entry per keyword block, named by keyword, id and title; past
  10,000 blocks one line says why (D3)".

---

### Task 7: Field hints and the ruler action

**Files:**
- Modify: `src/deckcheck/navigate.py`, `src/deckcheck/lsp/features.py`, `src/deckcheck/lsp/server.py`
- Test: `tests/test_navigate.py`, `tests/test_lsp_features.py`

**Interfaces:**
- Produces: `navigate.MAX_HINTS = 2000`; `navigate.hints(src, first, last, params, long_deck) -> list[tuple[int,
  int, str]]` (line, M1 column, field name); `navigate.ruler(fields: list[Field]) -> str | None`.
- Produces: `features.inlay_hints(ls, path, rng) -> list[types.InlayHint] | None`;
  `features.ruler_action(ls, path, rng, uri) -> list[types.CodeAction]`.

- [ ] **Step 1: Write the failing tests**

```python
from deckcheck.navigate import MAX_HINTS, hints, ruler


def test_hints_name_each_field_in_the_range(tmp_path):
    nav = nav_of(model(tmp_path))
    got = hints(nav.tree.files[0].source, 6, 6, nav.params, nav.long_deck)
    assert got[:3] == [(6, 9, "pid"), (6, 19, "secid"), (6, 29, "mid")]


def test_hints_are_capped(tmp_path):
    nodes = "".join(i8(n) + f"{0.0:>16}" * 3 + "\n" for n in range(1, 2001))
    nav = nav_of(model(tmp_path, "*KEYWORD\n*NODE\n" + nodes + "*END\n", files={}))
    assert len(hints(nav.tree.files[0].source, 1, 3000, nav.params, nav.long_deck)) == MAX_HINTS


def test_ruler_of_a_part_card(tmp_path):
    main = model(tmp_path)
    nav = nav_of(main)
    block = block_at(nav.tree.files[0].source, 6)
    assert ruler(fields_between(block, 6, 6, {}, False)) == (
        "$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid")


def test_ruler_names_are_cut_to_leave_a_space():
    f = Field("averylongname", 1, 0, 0, None, 1, {"name": "averylongname", "offset": 0, "width": 8})
    g = Field("anotherlongname", 1, 8, 8, None, 1, {"name": "anotherlongname", "offset": 8, "width": 8})
    assert ruler([f, g]) == "$# avery another"
```

Protocol tests:

```python
@pytest.mark.asyncio
async def test_inlay_hints_for_the_visible_range(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        got = await client.text_document_inlay_hint_async(types.InlayHintParams(
            types.TextDocumentIdentifier(uri(main)), types.Range(pos(16, 0), pos(16, 80))))
        assert [h.label for h in got][:3] == ["eid", "pid", "n1"]


@pytest.mark.asyncio
async def test_insert_field_ruler_above_a_card(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        acts = await client.text_document_code_action_async(types.CodeActionParams(
            types.TextDocumentIdentifier(uri(main)), types.Range(pos(6, 3), pos(6, 3)), types.CodeActionContext([])))
        assert [a.title for a in acts] == ["Insert field ruler"]
        edit = acts[0].edit.changes[uri(main)][0]
        assert edit.range.start == pos(6, 0) and edit.new_text.startswith("$#     pid     secid       mid")


@pytest.mark.asyncio
async def test_no_ruler_on_a_comma_separated_card(tmp_path):
    main = model(tmp_path, MAIN.replace(i10(1, 1, 1), "1,1,1"))
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        acts = await client.text_document_code_action_async(types.CodeActionParams(
            types.TextDocumentIdentifier(uri(main)), types.Range(pos(6, 0), pos(6, 0)), types.CodeActionContext([])))
        assert not acts
```

- [ ] **Step 2: Run.** Expected: FAIL on the imports.

- [ ] **Step 3: Implement.** `navigate.py`:

```python
MAX_HINTS = 2000  # spec §5.6


def hints(src: SourceFile, first: int, last: int, params: dict, long_deck: bool) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    i = max(bisect.bisect_right(src.blocks, first, key=lambda b: b.line) - 1, 0)
    for b in src.blocks[i:]:
        if b.line > last or len(out) >= MAX_HINTS:
            break
        fields = fields_between(b, first, last, params, long_deck) or []
        out += [(f.line, f.start, f.name) for f in fields]
    return out[:MAX_HINTS]


def ruler(fields: list[Field]) -> str | None:
    """A `$#` comment naming each field over its columns, as pre-processors write it. None without fixed columns."""
    if not fields or any("offset" not in f.spec for f in fields):
        return None
    text = ""
    for f in sorted(fields, key=lambda f: f.spec["offset"]):
        w, at = f.spec["width"], f.spec["offset"]
        name = f.name[:w - 3] if at == 0 else f.name[:w - 1]  # "$#" takes the first slot's first two columns
        text = text.ljust(at) + name.rjust(w)
    return "$#" + text[2:]
```

A comma-separated card's fields still carry `offset` in their spec, so whether a card has columns is the caller's
decision: `features.ruler_action` offers nothing when `card.free` or `is_long(block, nav.long_deck)` (D8), and
`test_no_ruler_on_a_comma_separated_card` pins it there.

`features.py`:

```python
def inlay_hints(ls, path: Path, rng: types.Range) -> list[types.InlayHint] | None:
    def run():
        vs = views(ls, path)
        if not vs:
            return None
        v = vs[0]
        out = []
        for line, col, name in hints(v.src, rng.start.line + 1, rng.end.line + 1, v.nav.params, v.nav.long_deck):
            text = line_text(v.src, line) or ""
            out.append(types.InlayHint(types.Position(line - 1, utf16_column(text, col, v.disk)), name,
                                       padding_right=True))
        return out
    return guarded(ls, run)


def ruler_action(ls, path: Path, rng: types.Range, uri: str) -> list[types.CodeAction]:
    def run():
        vs = views(ls, path)
        if not vs or vs[0].disk:  # an unsynced file: its line endings aren't known (D8)
            return []
        v, line = vs[0], rng.start.line + 1
        block = block_at(v.src, line)
        card = card_at(block, line) if block else None
        if card is None or card.free or is_long(block, v.nav.long_deck):
            return []
        text = ruler(fields_between(block, line, line, v.nav.params, v.nav.long_deck) or [])
        if text is None:
            return []
        eol = "\r\n" if "\r\n" in (ls.ws.source(path) or "")[:65536] else "\n"
        at = types.Range(types.Position(line - 1, 0), types.Position(line - 1, 0))
        return [types.CodeAction("Insert field ruler", kind=types.CodeActionKind.RefactorRewrite,
                                 edit=types.WorkspaceEdit(changes={uri: [types.TextEdit(at, text + eol)]}))]
    return guarded(ls, run) or []
```

(imports: `hints`, `ruler` from navigate; `is_long` from `deckcheck.fields`.) Register `TEXT_DOCUMENT_INLAY_HINT`
and `TEXT_DOCUMENT_CODE_ACTION` (with
`types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.RefactorRewrite])`). In `_publish`, after a
successful result, if the client declared `workspace.inlayHint.refreshSupport`, send
`ls.workspace_inlay_hint_refresh(None)` so hints computed before the check are redrawn.

- [ ] **Step 4: Run** the tests and the suite. Measure `hints` for lines 1,000,000–1,000,060 of a generated
  1.5 M-node block (local, not committed): Expected under 100 ms.

- [ ] **Step 5: Commit** "Field hints for the visible range, at most 2,000, and Insert field ruler on fixed-column
  cards (spec §5.6)".

---

### Task 8: VS Code client check and the user docs

**Files:**
- Modify: `editors/vscode/test/integration/suite.ts`, `docs/manual/README.md`, `docs/roadmap.md`, `README.md`
- Test: `npm run test:vscode` (from `editors/vscode`)

- [ ] **Step 1: Write the failing integration test** (in `tests`, after `squigglesOnSeededMistakes`; the workspace's
  `main.k` includes `mat.k` and `part.k`, written by `run.ts`):

```typescript
  ["hoverAndDefinitionAcrossIncludes", async () => {
    const uri = await open("part.k");
    await until(() => ext().exports.lastStatusMain().endsWith("main.k") || undefined, 30_000);
    const at = new vscode.Position(3, 29);                      // part.k line 4: the part card, mid's value
    const hovers = await until(async () => {
      const h = await vscode.commands.executeCommand<vscode.Hover[]>("vscode.executeHoverProvider", uri, at);
      return h.length ? h : undefined;
    });
    assert.ok(JSON.stringify(hovers[0].contents).includes("MAT 1"));
    const defs = await vscode.commands.executeCommand<vscode.Location[]>("vscode.executeDefinitionProvider", uri, at);
    assert.ok(defs[0].uri.fsPath.endsWith("mat.k") && defs[0].range.start.line === 2);
  }],
```

`until` takes a synchronous function today; add an `untilAsync` beside it with the same loop that awaits `f()`.

- [ ] **Step 2: Run** `npm run compile && npm run test:vscode`. Expected: FAIL only if the client blocks the
  requests; with the Python side done it should PASS at once. A pass here proves the language client forwards the
  new requests with no client change: say so in the report. If it fails, look at the middleware in
  `extension.ts:223` before changing anything.

- [ ] **Step 3: Docs.**
  - Manual: a section "Navigate a model" after "Reading a finding": hover, F12 / Ctrl+click, Shift+F12, the
    Outline panel, hold Ctrl+Alt for field names, the lightbulb's "Insert field ruler"; D1, D2, D5 and D8 under
    "Known limits". Screenshots: none in this plan (re-shooting needs the throwaway rig; backlog item stays open).
  - Roadmap: M2 row "done"; move M2c from Next to "What works today".
  - README: "In VS Code" mentions navigation in one sentence and links to the manual section.

- [ ] **Step 4: Commit** "VS Code test of hover and definition; manual, roadmap and README for navigation".

---

### Task 9: Measured gates, report, backlog

**Files:**
- Modify: `tests/test_lsp_stress.py`, `editors/vscode/test/integration/suite.ts` (harm tests)
- Create: `docs/m2c-navigation.md`
- Modify: `docs/specs/2026-10-30-m2-vscode-design.md` (status line), `docs/backlog.md`

- [ ] **Step 1: Hostile files** (default suite, not stress-marked):

```python
@pytest.mark.parametrize("kind", ["long_line", "binary", "nul"])
@pytest.mark.asyncio
async def test_features_on_hostile_files(tmp_path, kind):
    body = {"long_line": b"*KEYWORD\n*NODE\n" + b"1" * 2**20 + b"\n*END\n",
            "binary": bytes(range(256)) * 4096,
            "nul": b"*KEYWORD\n*PART\n\x00\x00\x00\n*END\n"}[kind]
    (tmp_path / "main.k").write_bytes(body)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await asyncio.sleep(2)
        for line in (1, 2, 3):
            t = time.monotonic()
            await hover(client, tmp_path / "main.k", line, 5)
            await definition(client, tmp_path / "main.k", line, 5)
            await symbols(client, tmp_path / "main.k")
            assert time.monotonic() - t < 1.0
        assert (await client.protocol.send_request_async("deckcheck/ping", {}))["ok"]
```

- [ ] **Step 2: Corpus timings** (marked `corpus`, run alone, under the 2 GB watchdog that the server already
  enforces):

```python
def _most_used_part(big: Path) -> tuple[int, int, int]:
    """(pid, line, column) of the first shell element of the part with the most shells, from the deck text,
    streamed: a second 1 GB parse in the test process would break the 2 GB lab cap."""
    counts, first, block = {}, {}, b""
    with open(big, "rb") as fh:
        for n, raw in enumerate(fh, start=1):
            if raw.startswith(b"*"):
                block = raw[1:].split()[0].upper() if raw[1:].split() else b""
            elif block == b"ELEMENT_SHELL" and not raw.startswith(b"$") and b"," not in raw:
                slot = raw[8:16]
                pid = slot.strip()
                if pid.isdigit():
                    counts[pid] = counts.get(pid, 0) + 1
                    first.setdefault(pid, (n, 8 + len(slot) - len(slot.lstrip())))
    pid = max(counts, key=counts.get)
    return int(pid), *first[pid]


async def _timed(coro) -> tuple[object, float]:
    t = time.perf_counter()
    got = await coro
    return got, (time.perf_counter() - t) * 1000


@pytest.mark.corpus
@pytest.mark.asyncio
async def test_navigation_on_the_yaris():
    main = Path(os.path.abspath(fetch(_entry("ccsa-yaris"))))
    big, sets = main.parent / "yaris-detailed-v2j.key", main.parent / "set-yaris-detailed-v2j.key"
    pid, line, col = _most_used_part(big)
    async with session(main.parent) as client:
        open_doc(client, main)
        open_doc(client, sets)                              # keeps the model's parse while the big file is unsynced
        client.protocol.notify("deckcheck/check", {"uri": uri(main)})
        assert await _ends_well(client, main) == "checked"
        h, t_hover = await _timed(hover(client, big, line, col))
        d, t_def = await _timed(definition(client, big, line, col))
        r, t_refs = await _timed(references(client, big, line, col))
        o, t_outline = await _timed(symbols(client, sets))
        mb = (await client.protocol.send_request_async("deckcheck/ping", {}))["mb"]
        print(f"yaris nav: part {pid}: hover {t_hover:.0f} ms, definition {t_def:.0f} ms, "
              f"references {len(r or [])} in {t_refs:.0f} ms; outline {len(o)} entries in {t_outline:.0f} ms; "
              f"server {mb:.0f} MB")
        assert h and f"PART {pid}" in h.contents.value and d and r
        assert t_hover < 100 and t_def < 100 and t_refs < 1000 and t_outline < 1000
```

  The helpers `hover`, `definition`, `references`, `symbols` come from `tests/test_lsp_features.py`. `deckcheck/ping`
  gains `"mb": rss_bytes() / 2**20` (from `lsp/__main__.py`). Record ids, counts and line numbers only (Global
  Constraints). If the most-used part's shells sit in a free-format block, `_most_used_part` skips it and picks
  from fixed-format blocks: say so in the report. Also report the server's memory after the check against M2b's
  figure: run the same test's check and ping on `main` from a second worktree (`git worktree add ../dc-main main`),
  alone, and remove the worktree after.

- [ ] **Step 3: Stress decks** (`DECKCHECK_STRESS=1`, local): on the generated several-hundred-MB single-file mesh
  (`test_huge_unsynced_mesh_checks_or_pauses`), after its check: hints for 60 lines in the middle of the node block
  < 100 ms; hover there < 100 ms; outline < 1 s.

- [ ] **Step 4: Harm gate re-run, alone.** Nothing else running (no reviewer, no other test). `npm run package`
  (rebuild the `.vsix` with bundled libs), then `DECKCHECK_HARM=1 npm run test:vscode`. All existing lines must
  pass: open on vs off within 10 % or 20 ms (small deck, Yaris main deck, 169 MB include, paired), activation
  < 100 ms, command round trip during a Yaris check < 100 ms. Add one harm test, `navigationDuringYarisCheck`:
  while a Yaris check runs, hover requests in `combine.key` return (nothing or the last result) in < 100 ms.

- [ ] **Step 5: Report** `docs/m2c-navigation.md`: what M2c delivers; every gate with its number (Steps 2–4) beside
  M2b's; rulings and D1–D8 as decided by Chintan; memory delta; what M3 can reuse (`navigate.py`). Spec status
  line: `M2c done <date> (docs/m2c-navigation.md)`. Backlog: the plan's deferred minors and declined rulings under a
  new `### M2c (navigation)` heading; mark the M2c product row done; add "Navigation deep in non-uniform blocks
  (D5)" and "Navigation while a big model is edited (D1)" as open items.

- [ ] **Step 6: Commit** "M2c gates, report and backlog". Then the final whole-branch review (fresh reviewer), its
  fix pass, and the branch decision with Chintan (superpowers:finishing-a-development-branch). No merge without his
  choice.
