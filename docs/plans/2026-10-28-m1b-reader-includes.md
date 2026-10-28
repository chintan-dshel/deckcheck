# M1b: Reader and include resolver — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read every file of a deck into keyword blocks and cards with exact line numbers, and follow its includes
the way LS-DYNA does. LS-DYNA itself decides every include rule on new torture decks; none is taken from memory.

**Architecture:**
- `deckcheck.reader.read_file(path)` turns one file into `Block`s (keyword name, line, resolved keyword data entry)
  holding `Card`s (line, raw text). It skips `$` comment lines, keeps blank lines as cards, and never interprets a
  keyword's meaning.
- `deckcheck.includes.resolve_tree(main)` reads the main file, follows `*INCLUDE` and `*INCLUDE_TRANSFORM` in
  reading order, and applies `*INCLUDE_PATH` / `*INCLUDE_PATH_RELATIVE`. It returns every file read, with its
  parent, include line and transform offsets, plus a problem list: missing files, cycles, and include forms it does
  not follow.
- The search order and edge cases are module constants in `includes.py`. Each names the torture case whose
  LS-DYNA verdict set it.
- `deckcheck.fields.card_values(card, fields)` reads a card's fields by the keyword data's column layout, or by
  comma position in free format. The resolver uses it only for `*INCLUDE_TRANSFORM` offsets; M1c's field reader
  extends it.

**Tech Stack:** Python 3.12, stdlib only at runtime. pytest. LS-DYNA R16.1 Student as referee
(`bakeoff/lsdyna_oracle.py`). psutil for the capped corpus run (bakeoff extra).

**Spec:** `docs/specs/2026-10-27-deckcheck-design.md` (B1′ revision). Sections 2, 4 (include resolver and reader
rows), 8, 11 (M1 done: `include_path`, `blank_title`, `long_format`, exact lines, VIVA+ 18/18 files, Yaris under
2 GB) and 12 (third question) bind this plan. M1a's findings (`docs/m1a-keyword-data.md` §4, item 6) bind the
transform offsets.

## Global Constraints

- deckcheck has **no runtime dependencies** (spec §9). psutil stays in the `bakeoff` extra.
- The reader never interprets keyword meaning on its own (spec §2). Include handling is structural and is the
  spec's named exception: the include resolver unit (spec §4).
- **Every include rule comes from an LS-DYNA run on a torture deck**, never from memory of the manual (spec §12).
- External decks are never committed. Results files hold names, counts and line numbers only.
- Corpus runs use a **2 GB** memory cap on the 7.7 GB laptop, each deck in a child process (process-tree RSS).
- Line numbers are 1-based. A column is a byte offset: files are decoded as Latin-1, one character per byte.
- No GitHub remote, no PyPI publish.
- Work on branch `m1b`, never directly on `main`. Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Deliberate deviation from spec §4:** the reader does **not** substitute `*PARAMETER` values. Substitution needs
field positions, so it moves to M1c's field reader. `*PARAMETER` blocks are read like any other block. Task 5
records this in the spec.

## Review Focus

1. **Latin-1 bytes Python treats as line breaks.** `str.splitlines()` breaks on `\x85`, `\x0b`, `\x0c` and
   `\x1c`–`\x1e`, which can occur in a Latin-1 title. Expected: they stay inside the card and line numbers stay
   exact. Pinned by `test_latin1_bytes_do_not_break_lines` (Task 2).
2. **Ragged file edges:** a last line without a newline, an empty file, text before the first keyword, a keyword
   line with trailing spaces and a `$` comment. Expected: the last card is kept, an empty file has no blocks,
   preamble text is ignored, and the name is clean. Pinned by `test_file_edges` (Task 2).
3. **The same file included twice.** That is not a cycle (LS-DYNA reads it twice, so its ids are defined twice).
   Expected: it appears twice in `Tree.files`, is read from disk once, and raises no problem. Pinned by
   `test_same_file_twice_is_not_a_cycle` (Task 3).
4. **Run from another working directory.** `deckcheck sub/dir/main.k` from elsewhere. Expected: includes resolve
   against the main deck's folder, not the working directory. Pinned by `test_relative_main_from_another_cwd`
   (Task 3).
5. **Reported paths.** VIVA+ writes `..\common\`, and dynars reported paths with a `\\?\` prefix. Expected: every
   path in a tree is absolute, normalised (no `..`, one separator style) and has no `\\?\` prefix. Pinned by
   `test_tree_paths_are_plain` (Task 3).

---

### Task 1: Ask LS-DYNA how it reads includes and `*END`

**Files:**
- Create: `tests/torture/make_include_cases.py`, 13 case folders `tests/torture/inc_*` and `tests/torture/end_*`,
  `bakeoff/referee_cases.py`
- Modify: `bakeoff/lsdyna_oracle.py` (timeout returns a verdict), `tests/test_lsdyna_oracle.py`,
  `tests/test_torture_layout.py` (case list), `tests/torture/{include_path,seeded_mistakes,crlf_seeded,latin1_seeded}/expected.toml`

**Interfaces:**
- Consumes: `bakeoff.lsdyna_oracle.lsdyna_reads(case_dir, timeout_s=120) -> tuple[bool, str]`.
- Produces: each case's `expected.toml` with `lsdyna_valid` (LS-DYNA's verdict), a `note` (the question, verdict
  and deciding log line) and a `[resolver]` table: `files` (paths relative to the case folder, posix, in reading
  order) and optional `problems` (list of `{kind, file, line, name}`). Tasks 2 and 3 test against these.

- [ ] **Step 1: Branch**

```bash
git checkout -b m1b
```

- [ ] **Step 2: Write the failing oracle test** (append to `tests/test_lsdyna_oracle.py`)

```python
import subprocess

import bakeoff.lsdyna_oracle as oracle


def test_timeout_is_a_rejection(monkeypatch, tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*END\n")

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(oracle.subprocess, "run", hang)
    ok, log = oracle.lsdyna_reads(tmp_path, timeout_s=1)
    assert ok is False and "timeout" in log
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_lsdyna_oracle.py::test_timeout_is_a_rejection -q -p no:cacheprovider`
Expected: FAIL with `TimeoutExpired`.

- [ ] **Step 3: Catch the timeout** in `bakeoff/lsdyna_oracle.py`, replacing the `proc = subprocess.run(...)`
  statement:

```python
        try:
            proc = subprocess.run([str(LSDYNA_EXE), "i=main.k", "ncpu=1"], cwd=work, env=env,
                                  capture_output=True, text=True, encoding="latin-1", timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False, f"timeout after {timeout_s} s"
```

Run the same test. Expected: PASS.

- [ ] **Step 4: Write the case generator** `tests/torture/make_include_cases.py`

Each case asks LS-DYNA one question. A "good" file defines material 1, which part 1 needs. A "bad" file defines
only material 2. If LS-DYNA reads the bad one, part 1 has no material and the run ends in error termination.
Which file LS-DYNA read therefore shows in its verdict.

```python
"""Write the include and *END torture cases. Each asks LS-DYNA one question about how it reads files.
Run once; output is committed. LS-DYNA's answers go into each case's expected.toml (M1b plan, Task 1)."""
from pathlib import Path

HERE = Path(__file__).parent

HEAD = "*KEYWORD\n*TITLE\ndeckcheck torture: {}\n*CONTROL_TERMINATION\n    1.0E-6\n"
PART = "*PART\nplate\n         1         1         1\n"
SECTION = "*SECTION_SHELL\n         1         2\n       1.0       1.0       1.0       1.0\n"
MAT = "*MAT_ELASTIC\n         {}   7.85E-9  210000.0       0.3\n"
MESH = ("*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2            10.0             0.0             0.0\n"
        "       3            10.0            10.0             0.0\n"
        "       4             0.0            10.0             0.0\n"
        "*ELEMENT_SHELL\n"
        "       1       1       1       2       3       4\n")
GOOD = "*KEYWORD\n" + MAT.format(1) + "*END\n"  # material 1: what part 1 needs
BAD = "*KEYWORD\n" + MAT.format(2) + "*END\n"   # material 2 only: reading this file leaves part 1 without material


def main_deck(title: str, includes: str, body: str = PART + SECTION + MESH) -> str:
    return HEAD.format(title) + includes + body + "*END\n"


def part_file(text: str) -> str:
    return "*KEYWORD\n" + text + "*END\n"


WITH_MAT = PART + SECTION + MAT.format(1) + MESH

CASES = {
    "inc_nested_sibling": {  # Is a nested include searched in the including file's folder?
        "main.k": main_deck("nested include beside its includer", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE\nb.k\n"),
        "sub/b.k": GOOD},
    "inc_nested_main": {  # Is a nested include searched in the main deck's folder?
        "main.k": main_deck("nested include beside main", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE\nb.k\n"),
        "b.k": GOOD},
    "inc_nested_both": {  # If both folders hold the file, which wins?
        "main.k": main_deck("nested include in both folders", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE\nb.k\n"),
        "sub/b.k": GOOD,
        "b.k": BAD},
    "inc_path_precedence": {  # Does an *INCLUDE_PATH folder win over the main deck's folder?
        "main.k": main_deck("include path precedence", "*INCLUDE_PATH\nlib\n*INCLUDE\nmat.k\n"),
        "mat.k": BAD,
        "lib/mat.k": GOOD},
    "inc_path_relative": {  # Is *INCLUDE_PATH_RELATIVE relative to the file holding it, or to the main deck?
        "main.k": main_deck("include path relative", "*INCLUDE\nsub/a.k\n"),
        "sub/a.k": part_file("*INCLUDE_PATH_RELATIVE\nlib\n*INCLUDE\nmat.k\n"),
        "sub/lib/mat.k": GOOD,
        "lib/mat.k": BAD},
    "inc_path_backslash": {  # VIVA+'s form: a Windows path with a trailing backslash
        "main.k": main_deck("include path with backslashes", "*INCLUDE_PATH\n.\\lib\\\n*INCLUDE\nmat.k\n"),
        "lib/mat.k": GOOD},
    "inc_path_late": {  # Does an *INCLUDE_PATH apply to an *INCLUDE that comes before it?
        "main.k": main_deck("include path after the include", "*INCLUDE\nmat.k\n*INCLUDE_PATH\nlib\n"),
        "lib/mat.k": GOOD},
    "inc_multi": {  # Does one *INCLUDE read several filename cards?
        "main.k": main_deck("two files on one include", "*INCLUDE\nmat.k\nsec.k\n", PART + MESH),
        "mat.k": GOOD,
        "sec.k": part_file(SECTION)},
    "inc_continuation": {  # Does a filename ending in ' +' continue on the next line?
        "main.k": main_deck("filename continued", "*INCLUDE\nsub/ +\nmat.k\n"),
        "sub/mat.k": GOOD},
    "inc_cycle": {  # What does LS-DYNA do with a.k -> b.k -> a.k?
        "main.k": main_deck("include cycle", "*INCLUDE\na.k\n", WITH_MAT),
        "a.k": part_file("*INCLUDE\nb.k\n"),
        "b.k": part_file("*INCLUDE\na.k\n")},
    "inc_transform": {  # *INCLUDE_TRANSFORM with node and element offsets, laid out like the Yaris
        "main.k": main_deck("include transform", "",
                            PART + SECTION + MAT.format(1)
                            + "*INCLUDE_TRANSFORM\nmesh.k\n       100       100\n\n\n\n"),
        "mesh.k": part_file(MESH)},
    "end_main": {  # Is text after *END in the main deck ignored?
        "main.k": main_deck("text after end", "", WITH_MAT) + "*NOT_A_KEYWORD\n         1\n"},
    "end_include": {  # Does *END in an include end only that file, the parent continuing after it?
        "main.k": main_deck("end inside an include", "*INCLUDE\nmat.k\n"),
        "mat.k": GOOD + "*NOT_A_KEYWORD\n         1\n"},
}

for name, files in CASES.items():
    for rel, text in files.items():
        path = HERE / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("latin-1"))  # '\n' endings on every platform
```

Run: `.venv/Scripts/python.exe tests/torture/make_include_cases.py`
Expected: 13 new folders. Check `inc_path_backslash/main.k` line 7 reads `.\lib\`, and `inc_transform/main.k`
has three blank lines after the offsets card.

- [ ] **Step 5: Write the referee script** `bakeoff/referee_cases.py`

```python
"""Ask LS-DYNA Student about named torture cases; print each verdict and, for rejections, the log tail."""
import sys
from pathlib import Path

from bakeoff.lsdyna_oracle import lsdyna_reads

for name in sys.argv[1:]:
    ok, log = lsdyna_reads(Path("tests/torture") / name)
    print(f"== {name}: {'accepted' if ok else 'rejected'}")
    if not ok:
        print(log)
```

- [ ] **Step 6: Run the referee**

Run:

```bash
.venv/Scripts/python.exe -m bakeoff.referee_cases inc_nested_sibling inc_nested_main inc_nested_both inc_path_precedence inc_path_relative inc_path_backslash inc_path_late inc_multi inc_continuation inc_cycle inc_transform end_main end_include > bakeoff/results/m1b_referee.txt
```

Expected: 13 verdicts. The license-manager message in a log is noise. For each rejection, find the deciding line:
`MATERIAL ID 1 does not exist`-style (the bad file was read), a file-open error (no file found), or an
unknown-keyword error.

- [ ] **Step 7: Record each verdict** in `tests/torture/<case>/expected.toml`, by this table

Every file has `lsdyna_valid` = the verdict, `findings = []`, and `note` = "Q: <question>. LS-DYNA R16.1
Student <date>: <verdict>; <deciding log line, if rejected>." Then `[resolver]` as below. **Stop** means: do not
guess. Stop the plan and report the log to Chintan, because no rule below explains it.

| Case | Accepted → `[resolver]`, constant | Rejected → `[resolver]`, constant |
|---|---|---|
| inc_nested_sibling | `files = ["main.k", "sub/a.k", "sub/b.k"]`; `SEARCH_INCLUDING_DIR = True` | `files = ["main.k", "sub/a.k"]`, `problems = [{kind = "missing", file = "sub/a.k", line = 3, name = "b.k"}]`; `False` |
| inc_nested_main | `files = ["main.k", "sub/a.k", "b.k"]`; `SEARCH_MAIN_DIR = True` | `files = ["main.k", "sub/a.k"]`, same `problems` shape; `False` |
| inc_nested_both | `files = ["main.k", "sub/a.k", "sub/b.k"]`; `INCLUDING_DIR_FIRST = True` | material error: `files = ["main.k", "sub/a.k", "b.k"]`; `False`. Must agree with the two rows above: if only one folder is searched, that folder's file is the one read |
| inc_path_precedence | `files = ["main.k", "lib/mat.k"]`; `PATH_BEFORE_DIRS = True` | material error: `files = ["main.k", "mat.k"]`; `False` |
| inc_path_relative | `files = ["main.k", "sub/a.k", "sub/lib/mat.k"]`; `PATH_RELATIVE_TO_FILE = True` | material error: `files = ["main.k", "sub/a.k", "lib/mat.k"]`; `False`. File-open error: **stop** |
| inc_path_backslash | `files = ["main.k", "lib/mat.k"]` | **stop** (VIVA+ relies on this form) |
| inc_path_late | `files = ["main.k", "lib/mat.k"]`; `PATH_APPLIES_EARLIER = True` | `files = ["main.k"]`, `problems = [{kind = "missing", file = "main.k", line = 7, name = "mat.k"}]`; `False` |
| inc_multi | `files = ["main.k", "mat.k", "sec.k"]`; `MULTI_FILENAME = True` | section error: `files = ["main.k", "mat.k"]`; `False` |
| inc_continuation | `files = ["main.k", "sub/mat.k"]`; `CONTINUATION = True` | `CONTINUATION = False`; `files` and `problems` as the resolver then gives them: the name `sub/ +` (line 7) missing, and with `MULTI_FILENAME` also `mat.k` (line 8) |
| inc_cycle | either verdict: `files = ["main.k", "a.k", "b.k"]`, `problems = [{kind = "cycle", file = "b.k", line = 3, name = "a.k"}]` | same |
| inc_transform | `files = ["main.k", "mesh.k"]` | **stop** |
| end_main | `files = ["main.k"]`; `STOP_AT_END = True` (reader) | unknown-keyword error: `files = ["main.k"]`; `STOP_AT_END = False` |
| end_include | `files = ["main.k", "mat.k"]` | **stop** if `end_main` was accepted (the two must agree); otherwise `files = ["main.k", "mat.k"]` |

Add a `[resolver]` table to the four existing cases with includes:
- `include_path`: `files = ["main.k", "sub/mat.k"]`.
- `seeded_mistakes`, `crlf_seeded`, `latin1_seeded`: `files = ["main.k"]`,
  `problems = [{kind = "missing", file = "main.k", line = 3, name = "missing_file.k"}]`. (M0's `findings` say
  line 2, the keyword line, for dynars. deckcheck points at the filename card, line 3, per spec §11.)

Write the 9 constants and their verdicts into the Task 5 report table as you go.

- [ ] **Step 8: Add the cases to the layout test**

In `tests/test_torture_layout.py`, extend `CASES` with:

```python
         "inc_nested_sibling", "inc_nested_main", "inc_nested_both", "inc_path_precedence", "inc_path_relative",
         "inc_path_backslash", "inc_path_late", "inc_multi", "inc_continuation", "inc_cycle", "inc_transform",
         "end_main", "end_include"]
```

(replacing the closing `]` of the current list).

Run: `.venv/Scripts/python.exe -m pytest tests/test_torture_layout.py tests/test_lsdyna_oracle.py -q -p no:cacheprovider`
Expected: all pass. The LS-DYNA test now also referees the 13 new cases and must agree with what you recorded.

- [ ] **Step 9: Commit**

```bash
git add tests/torture bakeoff/referee_cases.py bakeoff/lsdyna_oracle.py bakeoff/results/m1b_referee.txt tests/test_lsdyna_oracle.py tests/test_torture_layout.py
git commit -m "Ask LS-DYNA how it reads includes and *END: 13 referee cases"
```

---

### Task 2: The reader

**Files:**
- Create: `src/deckcheck/reader.py`
- Test: `tests/test_reader.py`

**Interfaces:**
- Consumes: `deckcheck.keywords.resolve(line: str) -> Resolved | None`; Task 1's `end_main` verdict.
- Produces:
  - `Card(line: int, text: str)`, a `NamedTuple` with property `free -> bool` (the card holds a comma).
  - `Block(name: str, line: int, resolved: Resolved | None, cards: list[Card])`. `name` is the keyword as
    written, uppercased, without `*`, format suffix or comment: `MAT_ELASTIC_TITLE`.
  - `SourceFile(path: Path, blocks: list[Block], end_line: int | None)`. `end_line` is the line of the `*END` that
    stopped reading, if any.
  - `read_file(path: Path) -> SourceFile`.

- [ ] **Step 1: Write the failing tests** `tests/test_reader.py`

```python
import tomllib
from pathlib import Path

from deckcheck.keywords import Resolved
from deckcheck.reader import Card, read_file

TORTURE = Path(__file__).parent / "torture"


def _read(case):
    return read_file(TORTURE / case / "main.k")


def _shape(source):
    return [(b.name, b.line, [c.line for c in b.cards]) for b in source.blocks]


def test_base_blocks_and_cards():
    src = _read("base")
    assert [b.name for b in src.blocks][:8] == ["KEYWORD", "TITLE", "CONTROL_TERMINATION", "PART", "SECTION_SHELL",
                                                "MAT_ELASTIC", "NODE", "ELEMENT_SHELL"]
    part = src.blocks[3]
    assert part.line == 7
    assert part.cards == [Card(9, "plate"), Card(11, "         1         1         1")]
    assert part.resolved == Resolved("PART", (), "")


def test_blank_title_is_a_card():
    assert _read("blank_title").blocks[3].cards[0] == Card(9, "")


def test_comment_lines_are_not_cards():
    blocks = {b.name: b for b in _read("comments").blocks}
    assert blocks["CONTROL_TERMINATION"].cards == [Card(7, "    1.0E-6")]
    assert blocks["MAT_ELASTIC"].cards == [Card(20, "         1   7.85E-9  210000.0       0.3")]
    assert [c.line for c in blocks["NODE"].cards] == [22, 24, 25, 26]


def test_crlf_reads_like_lf():
    crlf = _read("crlf")
    assert _shape(crlf) == _shape(_read("base"))
    assert not any("\r" in c.text for b in crlf.blocks for c in b.cards)


def test_latin1_title_keeps_its_bytes():
    assert _read("latin1").blocks[3].cards[0] == Card(9, "Pr\xfcfplatte")


def test_latin1_bytes_do_not_break_lines(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes(b"*KEYWORD\n*PART\nA\x85B\x0bC\x0cD\x1cE\n         1\n*END\n")
    assert read_file(deck).blocks[1].cards == [Card(3, "A\x85B\x0bC\x0cD\x1cE"), Card(4, "         1")]


def test_lowercase_and_title_option():
    src = _read("lowercase")
    assert src.blocks[5].name == "MAT_ELASTIC_TITLE"
    assert src.blocks[5].resolved == Resolved("MAT_ELASTIC", ("TITLE",), "")


def test_free_format_is_flagged_per_card():
    part = _read("free_format").blocks[3]
    assert part.cards == [Card(7, "plate"), Card(8, "1,1,1")]
    assert [c.free for c in part.cards] == [False, True]


def test_long_format_suffix():
    mat = _read("long_format").blocks[5]
    assert mat.name == "MAT_ELASTIC" and mat.resolved.format == "+"


def test_tabs_are_kept_raw():
    mat = next(b for b in _read("tabs").blocks if b.name == "MAT_ELASTIC")
    assert "\t" in mat.cards[0].text


def test_file_edges(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes(b"preamble text\n*KEYWORD\n*PART   $ trailing comment\nx")
    src = read_file(deck)
    assert [(b.name, b.line, b.cards) for b in src.blocks] == [("KEYWORD", 2, []), ("PART", 3, [Card(4, "x")])]
    empty = tmp_path / "empty.k"
    empty.write_bytes(b"")
    assert read_file(empty).blocks == [] and read_file(empty).end_line is None


def test_text_after_end_is_read_as_lsdyna_reads_it():
    lsdyna_ignores_it = tomllib.loads((TORTURE / "end_main" / "expected.toml").read_text(encoding="utf-8"))["lsdyna_valid"]
    names = [b.name for b in _read("end_main").blocks]
    assert ("NOT_A_KEYWORD" not in names) == lsdyna_ignores_it
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_reader.py -q -p no:cacheprovider`
Expected: FAIL (`No module named 'deckcheck.reader'`).

- [ ] **Step 2: Implement** `src/deckcheck/reader.py`

Set `STOP_AT_END` from Task 1's `end_main` verdict (accepted → `True`).

```python
"""Split a deck file into keyword blocks and cards, with positions. Never interprets a keyword's meaning (spec §2)."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from deckcheck.keywords import Resolved, resolve

STOP_AT_END = True  # torture end_main: LS-DYNA ignores text after *END


class Card(NamedTuple):
    line: int  # 1-based
    text: str  # without the line ending; one character per byte (Latin-1), so a column is a byte offset

    @property
    def free(self) -> bool:
        return "," in self.text


@dataclass
class Block:
    name: str
    line: int
    resolved: Resolved | None
    cards: list[Card] = field(default_factory=list)


@dataclass
class SourceFile:
    path: Path
    blocks: list[Block]
    end_line: int | None


def _lines(path: Path) -> list[str]:
    # split on '\n' only: str.splitlines() would also break on Latin-1 bytes such as \x85
    text = path.read_bytes().decode("latin-1")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


def _name(line: str) -> str:
    head = line.split("$", 1)[0][1:].split(None, 1)
    return head[0].rstrip("+-").upper() if head else ""


def read_file(path: Path) -> SourceFile:
    blocks: list[Block] = []
    for n, text in enumerate(_lines(path), start=1):
        if text.startswith("$"):
            continue
        if text.startswith("*"):
            name = _name(text)
            if name == "END" and STOP_AT_END:
                return SourceFile(path, blocks, n)
            blocks.append(Block(name, n, resolve(text)))
        elif blocks:
            blocks[-1].cards.append(Card(n, text))
    return SourceFile(path, blocks, None)
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_reader.py -q -p no:cacheprovider`
Expected: all pass. If `test_long_format_suffix` fails because `*MAT_ELASTIC +` gives a name with a trailing
space or `+`, the fault is in `_name`; fix it there, not in the test.

- [ ] **Step 3: Full suite, then commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: all pass, 2 xfailed.

```bash
git add src/deckcheck/reader.py tests/test_reader.py
git commit -m "Reader: blocks and cards with exact lines; blank cards kept; Latin-1 byte columns"
```

---

### Task 3: Include resolver

**Files:**
- Create: `src/deckcheck/fields.py`, `src/deckcheck/includes.py`
- Test: `tests/test_includes.py`
- Modify: `pyproject.toml` (marker `corpus`)

**Interfaces:**
- Consumes: `read_file`, `Card`, `Block`, `SourceFile` (Task 2); `deckcheck.keywords.load()`; Task 1's
  `[resolver]` tables and constants.
- Produces:
  - `deckcheck.fields.card_values(card: Card, fields: list[dict]) -> dict[str, str]`: field name → stripped text.
  - `Problem(kind: str, file: Path, line: int, columns: tuple[int, int], name: str)`, frozen. `kind` is
    `"missing"`, `"cycle"`, `"unfollowed"` (an `*INCLUDE_*` form deckcheck does not read, e.g. `INCLUDE_BINARY`,
    `INCLUDE_AUTO_OFFSET`) or `"unread"` (a transform offset that is not an integer). `columns` is the 0-based
    `[start, end)` span of `name` on `line`.
  - `FileNode(path: Path, source: SourceFile, parent: int | None, line: int | None, offsets: dict[str, int])`.
    `line` is the filename card in the parent. `offsets` are this include's own `*INCLUDE_TRANSFORM` offsets by
    field name (`idnoff` … `idroff`), all eight present, `{}` for a plain include. Nested transforms are **not**
    composed here: M1c composes along `parent` once LS-DYNA has shown how.
  - `Tree(files: list[FileNode], problems: list[Problem])`. `files[0]` is the main deck; order is reading order.
  - `resolve_tree(main: Path) -> Tree`. Raises `FileNotFoundError` if `main` is not a file.

- [ ] **Step 1: Write the failing tests** `tests/test_includes.py`

```python
import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.includes import Problem, resolve_tree

TORTURE = Path(os.path.abspath(Path(__file__).parent / "torture"))
VIVA = Path(__file__).parents[1] / ".corpus" / "vivaplus-50M-seated-v2.0.2"
OFFSETS = ["idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff", "iddoff", "idroff"]


def _expected(case):
    return tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))


RESOLVER_CASES = sorted(p.name for p in TORTURE.iterdir()
                        if (p / "expected.toml").exists() and "resolver" in _expected(p.name))


def _rel(path, root):
    return Path(path).relative_to(root).as_posix()


@pytest.mark.parametrize("case", RESOLVER_CASES)
def test_resolver_follows_lsdyna(case):
    root, exp = TORTURE / case, _expected(case)["resolver"]
    tree = resolve_tree(root / "main.k")
    assert [_rel(f.path, root) for f in tree.files] == exp["files"]
    got = [{"kind": p.kind, "file": _rel(p.file, root), "line": p.line, "name": p.name} for p in tree.problems]
    assert got == exp.get("problems", [])


def test_problem_columns_span_the_name():
    tree = resolve_tree(TORTURE / "seeded_mistakes" / "main.k")
    assert tree.problems[0].columns == (0, len("missing_file.k"))


def test_transform_offsets_by_name():
    node = resolve_tree(TORTURE / "inc_transform" / "main.k").files[1]
    assert node.line == 15
    assert node.offsets == {name: 100 if name in ("idnoff", "ideoff") else 0 for name in OFFSETS}


def test_plain_include_has_no_offsets():
    assert resolve_tree(TORTURE / "include_path" / "main.k").files[1].offsets == {}


@pytest.mark.parametrize("case", RESOLVER_CASES)
def test_tree_paths_are_plain(case):
    for f in resolve_tree(TORTURE / case / "main.k").files:
        s = str(f.path)
        assert f.path.is_absolute() and not s.startswith("\\\\?\\") and s == os.path.normpath(s), s


def test_same_file_twice_is_not_a_cycle(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE\nc.k\n*INCLUDE\nc.k\n*END\n")
    (tmp_path / "c.k").write_text("*KEYWORD\n*END\n")
    tree = resolve_tree(tmp_path / "main.k")
    assert [f.path.name for f in tree.files] == ["main.k", "c.k", "c.k"]
    assert tree.problems == []
    assert tree.files[1].source is tree.files[2].source


def test_relative_main_from_another_cwd(monkeypatch):
    monkeypatch.chdir(TORTURE.parent)
    tree = resolve_tree(Path("torture/include_path/main.k"))
    assert [f.path.name for f in tree.files] == ["main.k", "mat.k"] and tree.problems == []


def test_unfollowed_include_forms_are_reported(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE_BINARY\nx.bin\n*END\n")
    tree = resolve_tree(tmp_path / "main.k")
    assert tree.problems == [Problem("unfollowed", tree.files[0].path, 2, (1, 15), "INCLUDE_BINARY")]


def test_missing_main_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_tree(tmp_path / "nope.k")


@pytest.mark.corpus
@pytest.mark.skipif(not VIVA.exists(), reason="VIVA+ not downloaded")
def test_vivaplus_loads_all_18_files():
    (root,) = VIVA.glob("*/model/50M-seated/vivaplus-50M.key")
    tree = resolve_tree(root)
    assert len(tree.files) == 18
    assert [p for p in tree.problems if p.kind != "unfollowed"] == []
```

In `pyproject.toml`, add `"corpus: needs a downloaded corpus deck"` to `markers`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_includes.py -q -p no:cacheprovider`
Expected: FAIL (`No module named 'deckcheck.includes'`).

- [ ] **Step 2: Implement** `src/deckcheck/fields.py`

```python
"""Field values of a card, by the keyword data's column layout (fixed format) or by comma position (free format).
M1c extends this into the full field reader (long format, *PARAMETER substitution, conditional cards)."""
from deckcheck.reader import Card


def card_values(card: Card, fields: list[dict]) -> dict[str, str]:
    if card.free:
        parts = card.text.split(",")
        return {f["name"]: parts[i].strip() for i, f in enumerate(fields) if i < len(parts)}
    return {f["name"]: card.text[f["offset"]:f["offset"] + f["width"]].strip() for f in fields}
```

- [ ] **Step 3: Implement** `src/deckcheck/includes.py`

Set the eight constants from Task 1's verdicts (the values below are the hypotheses the cases test).

```python
"""Follow a deck's includes in LS-DYNA's reading order. Every rule here was decided by LS-DYNA on the torture
cases named beside it (docs/m1b-reader-includes.md), not taken from memory."""
import os
from dataclasses import dataclass
from pathlib import Path

from deckcheck.fields import card_values
from deckcheck.keywords import load
from deckcheck.reader import Block, Card, SourceFile, read_file

SEARCH_INCLUDING_DIR = True   # inc_nested_sibling
SEARCH_MAIN_DIR = True        # inc_nested_main
INCLUDING_DIR_FIRST = True    # inc_nested_both
PATH_BEFORE_DIRS = False      # inc_path_precedence
PATH_RELATIVE_TO_FILE = True  # inc_path_relative
PATH_APPLIES_EARLIER = False  # inc_path_late
MULTI_FILENAME = True         # inc_multi
CONTINUATION = True           # inc_continuation

FOLLOWED = ("INCLUDE", "INCLUDE_TRANSFORM")
PATHS = ("INCLUDE_PATH", "INCLUDE_PATH_RELATIVE")


@dataclass(frozen=True)
class Problem:
    kind: str
    file: Path
    line: int
    columns: tuple[int, int]
    name: str


@dataclass
class FileNode:
    path: Path
    source: SourceFile
    parent: int | None
    line: int | None
    offsets: dict[str, int]


@dataclass
class Tree:
    files: list[FileNode]
    problems: list[Problem]


def _norm(path) -> Path:
    # abspath + normpath, never Path.resolve(): resolve() can add a \\?\ prefix on Windows
    return Path(os.path.normpath(os.path.abspath(path)))


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


def _span(text: str) -> tuple[int, int]:
    return len(text) - len(text.lstrip()), len(text.rstrip())


def _filenames(cards: list[Card]) -> list[tuple[Card, str, int]]:
    """(first card, filename, index of the next card) for each filename; ' +' continues a name on the next card."""
    out, parts, first = [], [], None
    for i, card in enumerate(cards):
        text = card.text.rstrip()
        if not text and first is None:
            continue
        first = first or card
        if CONTINUATION and text.endswith(" +"):
            parts.append(text[:-2].strip())
            continue
        parts.append(text.strip())
        out.append((first, "".join(parts), i + 1))
        parts, first = [], None
    return out


def _locate(name: str, including_dir: Path, main_dir: Path, paths: list[Path]) -> Path | None:
    rel = Path(name.replace("\\", "/"))
    if rel.is_absolute():
        dirs = [Path()]
    else:
        own = [including_dir] if SEARCH_INCLUDING_DIR else []
        top = [main_dir] if SEARCH_MAIN_DIR else []
        dirs = own + top if INCLUDING_DIR_FIRST else top + own
        dirs = paths + dirs if PATH_BEFORE_DIRS else dirs + paths
    for d in dirs:
        candidate = _norm(d / rel)
        if candidate.is_file():
            return candidate
    return None


def _offsets(tree: Tree, node: FileNode, block: Block, start: int) -> dict[str, int]:
    layout = load()["keywords"]["INCLUDE_TRANSFORM"]["cards"][1:3]  # the idnoff... and idroff cards
    out: dict[str, int] = {}
    for spec, card in zip(layout, block.cards[start:start + 2] + [Card(0, "")] * 2):
        fields = [f for f in spec["fields"] if f["name"].startswith("id") and f["name"].endswith("off")]
        for name, value in card_values(card, fields).items():
            try:
                out[name] = int(value) if value else 0
            except ValueError:
                tree.problems.append(Problem("unread", node.path, card.line, _span(card.text), value))
                out[name] = 0
    return out


def _walk(tree: Tree, index: int, chain: list[str], main_dir: Path, paths: list[Path],
          cache: dict[str, SourceFile]) -> None:
    node = tree.files[index]
    for block in node.source.blocks:
        if block.name in PATHS:
            relative = block.name == "INCLUDE_PATH_RELATIVE" and PATH_RELATIVE_TO_FILE
            base = node.path.parent if relative else main_dir
            for card in block.cards:
                if card.text.strip():
                    d = _norm(base / card.text.strip().replace("\\", "/"))
                    if d not in paths:
                        paths.append(d)
        elif block.name in FOLLOWED:
            names = _filenames(block.cards)
            if block.name == "INCLUDE_TRANSFORM" or not MULTI_FILENAME:
                names = names[:1]
            for card, name, after in names:
                found = _locate(name, node.path.parent, main_dir, paths)
                if found is None:
                    tree.problems.append(Problem("missing", node.path, card.line, _span(card.text), name))
                    continue
                if _key(found) in chain:
                    tree.problems.append(Problem("cycle", node.path, card.line, _span(card.text), name))
                    continue
                offsets = _offsets(tree, node, block, after) if block.name == "INCLUDE_TRANSFORM" else {}
                if _key(found) not in cache:
                    cache[_key(found)] = read_file(found)
                tree.files.append(FileNode(found, cache[_key(found)], index, card.line, offsets))
                _walk(tree, len(tree.files) - 1, chain + [_key(found)], main_dir, paths, cache)
        elif block.name.startswith("INCLUDE"):
            tree.problems.append(Problem("unfollowed", node.path, block.line, (1, 1 + len(block.name)), block.name))


def _build(main: Path, paths: list[Path], cache: dict[str, SourceFile]) -> Tree:
    if _key(main) not in cache:
        cache[_key(main)] = read_file(main)
    tree = Tree([FileNode(main, cache[_key(main)], None, None, {})], [])
    _walk(tree, 0, [_key(main)], main.parent, paths, cache)
    return tree


def resolve_tree(main: Path) -> Tree:
    main = _norm(main)
    if not main.is_file():
        raise FileNotFoundError(main)
    cache: dict[str, SourceFile] = {}
    paths: list[Path] = []
    tree = _build(main, paths, cache)
    if PATH_APPLIES_EARLIER and paths:
        tree = _build(main, paths, cache)  # second pass: every *INCLUDE_PATH known from the start
    return tree
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_includes.py -q -p no:cacheprovider`
Expected: all pass. A failing `test_resolver_follows_lsdyna[<case>]` means a constant disagrees with Task 1's
verdict, or the code cannot express what LS-DYNA does. Fix the constant in the first case. In the second, stop and
report: a new rule needs a decision, not a patch.

- [ ] **Step 4: Full suite, then commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: all pass, 2 xfailed.

```bash
git add src/deckcheck/fields.py src/deckcheck/includes.py tests/test_includes.py pyproject.toml
git commit -m "Include resolver: LS-DYNA's search order, cycles, transform offsets by name"
```

---

### Task 4: The corpus under a 2 GB cap

**Files:**
- Create: `bakeoff/read_tree.py`, `bakeoff/m1b_corpus.py`, `bakeoff/results/m1b_reader.jsonl`
- Modify: `bakeoff/run.py` (`run_one` takes the module to run)
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `resolve_tree` (Task 3); `bakeoff.run.run_one`, `TORTURE`, `MANIFEST`; `bakeoff.corpus.fetch`,
  `load_manifest`.
- Produces: `run_one(deck, cap_mb=4096, timeout_s=1800, module="bakeoff.probe") -> dict`; one JSON line per deck
  with `files`, `offsets`, `problems`, `blocks`, `cards`, `seconds`, `peak_mb`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_run.py`)

```python
from pathlib import Path

from bakeoff.run import run_one


def test_run_one_runs_the_named_module():
    row = run_one(Path("tests/torture/include_path/main.k"), cap_mb=2048, module="bakeoff.read_tree")
    assert row["files"] == ["main.k", "sub/mat.k"] and row["problems"] == [] and row["peak_mb"] > 0
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_run.py -q -p no:cacheprovider`
Expected: FAIL (`unexpected keyword argument 'module'`).

- [ ] **Step 2: Implement**

In `bakeoff/run.py`, change the signature and the `Popen` line of `run_one`:

```python
def run_one(deck: Path, cap_mb: int = 4096, timeout_s: float = 1800, module: str = "bakeoff.probe") -> dict:
```

```python
        proc = subprocess.Popen([sys.executable, "-m", module, str(deck), str(out)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
```

`bakeoff/read_tree.py`:

```python
"""Read one deck's include tree with deckcheck and write a summary JSON: python -m bakeoff.read_tree <deck> <out>."""
import json
import os
import sys
import time
from pathlib import Path

from deckcheck.includes import resolve_tree

deck, out = Path(sys.argv[1]), Path(sys.argv[2])
start = time.monotonic()
tree = resolve_tree(deck)
root = os.path.dirname(os.path.abspath(deck))


def rel(p):
    return Path(os.path.relpath(p, root)).as_posix()


out.write_text(json.dumps({
    "deck": str(deck),
    "files": [rel(f.path) for f in tree.files],
    "offsets": {rel(f.path): f.offsets for f in tree.files if any(f.offsets.values())},
    "problems": [{"kind": p.kind, "file": rel(p.file), "line": p.line, "name": p.name} for p in tree.problems],
    "blocks": sum(len(f.source.blocks) for f in tree.files),
    "cards": sum(len(b.cards) for f in tree.files for b in f.source.blocks),
    "seconds": round(time.monotonic() - start, 1),
}), encoding="utf-8")
```

`bakeoff/m1b_corpus.py`:

```python
"""M1b corpus run: deckcheck's reader and include resolver on every deck, each in a child process under 2 GB."""
import json
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST, TORTURE, run_one

OUT = Path("bakeoff/results/m1b_reader.jsonl")

if __name__ == "__main__":
    decks = [(p.parent.name, p) for p in sorted(TORTURE.glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(MANIFEST)]
    with open(OUT, "w", encoding="utf-8") as f:
        for name, deck in decks:
            row = {"name": name, **run_one(deck, cap_mb=2048, module="bakeoff.read_tree")}
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(name, row.get("error") or f"{len(row['files'])} files, {len(row['problems'])} problems",
                  row["peak_mb"], row.get("seconds"))
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_run.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 3: Run the corpus**

Run: `.venv/Scripts/python.exe -m bakeoff.m1b_corpus`
Expected, and check each:
- no row has `error` (crash, cap or timeout);
- VIVA+: 18 files, no `missing` / `cycle` / `unread`;
- Yaris: files `combine.key`, `yaris-detailed-v2j.key`, `set-yaris-detailed-v2j.key`, `wall.key`, with
  `wall.key` offsets all eight `10000000`; record its `peak_mb` and `seconds`;
- every torture row matches its `[resolver]` table.

If the Yaris exceeds 2 GB, stop and report: the reader's memory design (a `Card` per line) needs a decision.

- [ ] **Step 4: Judge every problem**

For each `missing`, `cycle` or `unread` problem on a corpus deck, open the deck at that line. It is either a real
defect in that deck (the file really is absent; record it as an expected finding for M1c's DC004) or a resolver
bug. A resolver bug gets a failing test in `tests/test_includes.py` first, then the fix, then a rerun of step 3.
List `unfollowed` problems by keyword with counts: M1c needs them, because ids in unfollowed files are invisible.

- [ ] **Step 5: Commit**

```bash
git add bakeoff/run.py bakeoff/read_tree.py bakeoff/m1b_corpus.py bakeoff/results/m1b_reader.jsonl tests/test_run.py
git commit -m "M1b corpus run: reader and includes on all tiers under 2 GB"
```

---

### Task 5: Report and gate

**Files:**
- Create: `docs/m1b-reader-includes.md`
- Modify: `docs/specs/2026-10-27-deckcheck-design.md` (§4 reader row; §12 third question)

- [ ] **Step 1: Write the report** `docs/m1b-reader-includes.md`:
1. **Verdict** in three lines: what the reader and resolver do, and whether VIVA+ and the Yaris load.
2. **What LS-DYNA decided:** one row per Task 1 case: question / verdict / deciding log line / rule adopted
   (constant and value).
3. **Corpus:** per tier: decks, files, blocks, cards, problems by kind, peak MB and seconds (the Yaris on its
   own row); each judged problem from Task 4 step 4.
4. **Spec §11 progress:** which of the seven M0 defects now pass (`include_path`, `blank_title`, `long_format`
   and the `\\?\` prefix and line-0 include report), and which wait for M1c (`_ID`, ICFD, misread field,
   `part_inertia`).
5. **What this means for M1c:** `*PARAMETER` substitution moved to the field reader; long format beyond the `+`
   suffix (`*KEYWORD LONG=`) is unhandled and absent from the corpus; nested transforms are not composed; how
   `unfollowed` includes must weaken DC001; the transform-offset-to-kind mapping (`idnoff` → nodes …) still needs
   evidence.

- [ ] **Step 2: Update the spec**
- §4, Reader row: replace "Substitutes `*PARAMETER` values where an id field holds `&name`." with
  "`*PARAMETER` substitution happens in the field reader (moved in M1b: it needs field positions)." Add to the
  Field reader row: "Substitutes `*PARAMETER` values where a field holds `&name`."
- §12, third bullet: append "**Answered in M1b (2026-10-xx):** by LS-DYNA R16.1 Student on the `inc_*` torture
  cases; the order is in `docs/m1b-reader-includes.md` §2."

- [ ] **Step 3: Full suite, commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: all pass, 2 xfailed.

```bash
git add docs/m1b-reader-includes.md docs/specs/2026-10-27-deckcheck-design.md
git commit -m "M1b report: reader, includes, LS-DYNA's include rules"
```

- [ ] **Step 4: Update the living report and memory**

Update the status line of the living report (https://claude.ai/artifact/A1dTFKALfhzDWuxSnqUGKS) to say M1b is done
and M1c is next. Update the project memory file.

- [ ] **Step 5: Gate**

Stop. Present the report to Chintan: LS-DYNA's include rules, the corpus results, the judged problems, and what
they mean for M1c. Do not start the M1c plan until he has read it.
