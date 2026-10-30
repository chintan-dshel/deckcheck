# M2a: Language Server and Squiggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python language server, `python -m deckcheck.lsp`, that publishes deckcheck's M1 diagnostics for a deck and its whole model while you edit, adapts to model size, and can never hurt the editor.

**Architecture:** The server imports the M1 core directly. A workspace layer holds unsaved text (the overlay), per-model parse caches and the main-deck map (light include walk). A single background runner checks one model at a time, live when the model is small and on save when it is big. The server runs at low CPU priority under a self-enforced memory budget. The M1 core gains only what this needs: reading from text, a source and cache for `resolve_tree`, and an include-only reader.

**Tech Stack:** Python 3.11+, pygls 2.1.1 (lsprotocol 2025.0.0), pytest, pytest-lsp 1.0.1 (dev only, brings pytest-asyncio).

**Spec:** `docs/specs/2026-10-30-m2-vscode-design.md` (bbae93d); parent `docs/specs/2026-10-27-deckcheck-design.md`.

## Global Constraints

- Do no harm (M2 spec §3) outranks every feature: no request waits for a check; one check at a time; below-normal priority; memory budget `memoryMB` default 2048, exit code 75 when exceeded.
- Runtime dependencies of the core stay none: pygls goes in the `lsp` extra only (`pip install deckcheck` unchanged).
- CLI output unchanged byte for byte: the existing torture harness (`tests/test_rules.py`) and CLI tests must stay green untouched.
- Never commit external decks; stress decks are generated in `tmp_path` at test time.
- Every stress run stays under the 2 GB lab cap (the server's own budget enforces it).
- Work on branch `m2`; commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test command: `.venv/Scripts/python -m pytest`.
- Names and branding: "deckcheck"; "for LS-DYNA" only as description.

## Review Focus

1. A UTF-8 accented character in a title or comment before a finding on the same line: the squiggle must sit under the right characters (Task 3 `test_utf8_prefix_shifts_column`).
2. An include edited in the editor but not saved, with the main deck checked: the unsaved text is what is checked (Task 6 `test_unsaved_include_is_checked`).
3. A modified include closed without saving: its overlay is dropped and the disk version applies again (Task 4 `test_close_drops_overlay_and_cache`).
4. Two edits during one slow check: only the newest result is published; an older one never overwrites it (Task 5 `test_result_of_superseded_request_is_discarded`).
5. A file in two models (shared materials in two load cases): one copy of identical findings, the rest naming their model (Task 3 `test_merge_dedupes_and_names_models`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/deckcheck/reader.py` (modify) | `read_file(path, text=None)`, `Block.text`, `read_includes` (include-only, streaming) |
| `src/deckcheck/includes.py` (modify) | `resolve_tree(main, source=None, cache=None, reader=read_file)` |
| `src/deckcheck/index.py` (modify) | `_long_deck` reads `Block.text`, not the disk |
| `src/deckcheck/diagnostics.py` (modify) | `Report.tree`, `Report.index` (kept for M2c) |
| `src/deckcheck/rules/__init__.py` (modify) | `check(main, source=None, cache=None)` |
| `src/deckcheck/lsp/__init__.py` | package marker |
| `src/deckcheck/lsp/convert.py` | M1 diagnostics → LSP: UTF-16 columns, related info, merge across models |
| `src/deckcheck/lsp/workspace.py` | settings, overlay, main-deck detection, per-model caches |
| `src/deckcheck/lsp/runner.py` | one-at-a-time adaptive check queue |
| `src/deckcheck/lsp/server.py` | protocol handlers |
| `src/deckcheck/lsp/__main__.py` | priority, memory watchdog, start on stdio |
| `tests/test_lsp_*.py` | one test file per module, plus `test_lsp_stress.py` |
| `docs/m2a-server-squiggles.md` | stage report |

---

### Task 1: Read from text; keep the keyword line

**Files:**
- Modify: `src/deckcheck/reader.py`
- Modify: `src/deckcheck/index.py:95-101`
- Test: `tests/test_reader.py`, `tests/test_index.py`

**Interfaces:**
- Produces: `read_file(path: Path, text: str | None = None) -> SourceFile`; `Block.text: str` (the keyword line as read, default `""`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_reader.py`)

```python
def test_read_from_text_matches_disk():
    path = TORTURE / "base" / "main.k"
    assert read_file(path, text=path.read_bytes().decode("latin-1")) == read_file(path)


def test_read_from_text_uses_the_text_not_the_disk():
    src = read_file(TORTURE / "base" / "main.k", text="*KEYWORD\n*PART\nedited\n         9         1         1\n")
    assert [b.name for b in src.blocks] == ["KEYWORD", "PART"]
    assert src.blocks[1].cards[1] == Card(4, "         9         1         1")


def test_block_keeps_its_keyword_line():
    assert _read("base").blocks[0].text.startswith("*KEYWORD")
```

Append to `tests/test_index.py` (add `from deckcheck.includes import resolve_tree` and `from deckcheck.index import _long_deck` if absent):

```python
def test_long_deck_reads_the_parsed_line_not_the_disk(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_text("*KEYWORD LONG=Y\n*END\n", encoding="latin-1")
    tree = resolve_tree(deck)
    deck.write_text("*KEYWORD\n*END\n", encoding="latin-1")
    assert _long_deck(tree) is True
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python -m pytest tests/test_reader.py tests/test_index.py -k "from_text or keyword_line or parsed_line" -v`
Expected: FAIL (`read_file() got an unexpected keyword argument 'text'`, `Block has no attribute text`, `_long_deck` returns False).

- [ ] **Step 3: Implement** in `src/deckcheck/reader.py`

```python
@dataclass
class Block:
    name: str
    line: int
    resolved: Resolved | None
    cards: list[Card] = field(default_factory=list)
    text: str = ""  # the keyword line as read (*KEYWORD LONG=Y needs it; M2 reads it instead of the disk)


def _split(text: str) -> list[str]:
    # split on '\n' only: str.splitlines() would also break on Latin-1 bytes such as \x85
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


def _lines(path: Path) -> list[str]:
    return _split(path.read_bytes().decode("latin-1"))


def read_file(path: Path, text: str | None = None) -> SourceFile:
    """text: the file's content when it must not come from disk (an editor's unsaved buffer, M2)."""
    blocks: list[Block] = []
    for n, line in enumerate(_lines(path) if text is None else _split(text), start=1):
        if line.startswith("$"):
            continue
        if line.startswith("*"):
            name = _name(line)
            if name == "END" and STOP_AT_END:
                return SourceFile(path, blocks, n)
            blocks.append(Block(name, n, resolve(line), text=line))
        elif blocks:
            blocks[-1].cards.append(Card(n, line))
    return SourceFile(path, blocks, None)
```

In `src/deckcheck/index.py` `_long_deck`, replace the disk read:

```python
        if block.name in ("KEYWORD", "KEYWORD_ID", "KEYWORD_JOBID"):  # LONG=Y on either: m1d_keyword_id_long
            return LONG_KEYWORD and "LONG=Y" in block.text.upper().replace(" ", "")
```

- [ ] **Step 4: Run the new tests, then the whole suite**

Run: `.venv/Scripts/python -m pytest tests/test_reader.py tests/test_index.py -v` → PASS.
Run: `.venv/Scripts/python -m pytest -q -m "not corpus and not install"` → all pass (CLI unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck/reader.py src/deckcheck/index.py tests/test_reader.py tests/test_index.py
git commit -m "M2a T1: read a deck from text; keep the keyword line; _long_deck no longer re-reads the disk"
```

---

### Task 2: Source, cache and include-only reading for the resolver

**Files:**
- Modify: `src/deckcheck/reader.py` (add `read_includes`, `_stream`)
- Modify: `src/deckcheck/includes.py:113-163`
- Modify: `src/deckcheck/diagnostics.py` (`Report.tree`, `Report.index`)
- Modify: `src/deckcheck/rules/__init__.py`
- Test: `tests/test_includes.py`, `tests/test_rules.py` (new tests only)

**Interfaces:**
- Consumes: `read_file(path, text=None)` (Task 1).
- Produces:
  - `Source = Callable[[Path], str | None]` in `deckcheck.includes`.
  - `resolve_tree(main: Path, source: Source | None = None, cache: dict[str, SourceFile] | None = None, reader: Callable[[Path, str | None], SourceFile] = read_file) -> Tree`. Cache keys are `includes._key(path)`; the caller drops an entry when that file changes.
  - `read_includes(path: Path, text: str | None = None) -> SourceFile` (only `*INCLUDE*` blocks; streams from disk).
  - `check(main: Path, source: Source | None = None, cache: dict | None = None) -> Report`, with `Report.tree` and `Report.index` set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rules.py`:

```python
MAIN = ("*KEYWORD\n*INCLUDE\nmat.k\n*PART\np\n         1         1        99\n"
        "*SECTION_SHELL\n         1\n*END\n")
MAT = "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n"


def _model(tmp):
    (tmp / "main.k").write_text(MAIN, encoding="latin-1")
    (tmp / "mat.k").write_text(MAT, encoding="latin-1")
    return tmp / "main.k", tmp / "mat.k"


def _dc001(report):
    return [d for d in report.diagnostics if d.code == "DC001"]


def _same(a, b) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def test_check_reads_an_unsaved_include_from_source(tmp_path):
    main, mat = _model(tmp_path)
    assert _dc001(check(main))
    edited = MAT.replace("         1", "        99", 1)
    assert not _dc001(check(main, source=lambda p: edited if _same(p, mat) else None))


def test_cache_keeps_parsed_files_until_the_caller_drops_them(tmp_path):
    main, mat = _model(tmp_path)
    cache = {}
    check(main, cache=cache)
    assert len(cache) == 2
    mat.write_text(MAT.replace("         1", "        99", 1), encoding="latin-1")
    assert _dc001(check(main, cache=cache))  # the stale parse is still used
    cache.pop(next(k for k in cache if k.endswith("mat.k")))
    assert not _dc001(check(main, cache=cache))


def test_report_carries_tree_and_index(tmp_path):
    main, _ = _model(tmp_path)
    r = check(main)
    assert len(r.tree.files) == 2 and r.index.tree is r.tree
```

Append to `tests/test_includes.py` (it already defines `TORTURE`; add the imports shown):

```python
import pytest

from deckcheck.reader import read_includes

LIGHT_CASES = sorted(p.parent.name for p in TORTURE.glob("*/main.k"))


def _shape(tree):
    return ([(f.path, f.parent, f.line, f.offsets) for f in tree.files],
            [(p.kind, p.file, p.line, p.name) for p in tree.problems])


@pytest.mark.parametrize("case", LIGHT_CASES)
def test_light_walk_finds_the_same_files(case):
    main = TORTURE / case / "main.k"
    assert _shape(resolve_tree(main, reader=read_includes)) == _shape(resolve_tree(main))


def test_read_includes_keeps_only_include_blocks():
    src = read_includes(TORTURE / "include_path" / "main.k")
    assert src.blocks and all(b.name.startswith("INCLUDE") for b in src.blocks)
```

Append to `tests/test_index_corpus.py` (corpus marker already applied there; it imports `fetch`, `load_manifest`, `MANIFEST`):

```python
from deckcheck.includes import resolve_tree
from deckcheck.reader import read_includes


@pytest.mark.parametrize("entry", load_manifest(MANIFEST), ids=lambda e: e.name)
def test_light_walk_finds_the_same_files_on_the_corpus(entry):
    main = fetch(entry)
    full, light = resolve_tree(main), resolve_tree(main, reader=read_includes)
    assert [f.path for f in light.files] == [f.path for f in full.files]
    assert [(p.kind, p.line) for p in light.problems] == [(p.kind, p.line) for p in full.problems]
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py tests/test_includes.py -k "source or cache or carries or light or read_includes" -v`
Expected: FAIL (`check() got an unexpected keyword argument`, `cannot import name 'read_includes'`).

- [ ] **Step 3: Implement**

`src/deckcheck/reader.py`, after `read_file`:

```python
def _stream(path: Path):
    with open(path, "rb") as f:
        for raw in f:  # binary iteration splits on b"\n" only, as _split does
            line = raw.decode("latin-1")
            if line.endswith("\n"):
                line = line[:-1]
            yield line[:-1] if line.endswith("\r") else line


def read_includes(path: Path, text: str | None = None) -> SourceFile:
    """Only the *INCLUDE* blocks, to find which files a deck pulls in without parsing it (M2 spec §4.4). Streams
    from disk, so a large mesh file is never held in memory."""
    blocks: list[Block] = []
    keep = False
    for n, line in enumerate(_stream(path) if text is None else _split(text), start=1):
        if line.startswith("$"):
            continue
        if line.startswith("*"):
            name = _name(line)
            if name == "END" and STOP_AT_END:
                return SourceFile(path, blocks, n)
            keep = name.startswith("INCLUDE")
            if keep:
                blocks.append(Block(name, n, resolve(line), text=line))
        elif keep:
            blocks[-1].cards.append(Card(n, line))
    return SourceFile(path, blocks, None)
```

`src/deckcheck/includes.py`: add `from collections.abc import Callable`, and

```python
Source = Callable[[Path], "str | None"]
Load = Callable[[Path], SourceFile]
```

Change `_walk` and `_build` to take `load: Load` as their last parameter, replacing `read_file(found)` / `read_file(main)` by `load(found)` / `load(main)` and passing `load` through the recursive `_walk` call. Replace `resolve_tree`:

```python
def resolve_tree(main: Path, source: Source | None = None, cache: dict[str, SourceFile] | None = None,
                 reader: Callable[[Path, str | None], SourceFile] = read_file) -> Tree:
    """source(path): a file's text when it must not come from disk (an editor's unsaved buffer); cache: parsed
    files kept between calls, keyed by _key(path), the caller dropping an entry when its file changes; reader:
    read_includes for the light walk that only finds files (M2 spec §4.4)."""
    main = _norm(main)
    if not main.is_file():
        raise FileNotFoundError(main)
    cache = {} if cache is None else cache

    def load(path: Path) -> SourceFile:
        return reader(path, source(path) if source else None)

    paths: list[Path] = []
    tree = _build(main, paths, cache, load)
    if PATH_APPLIES_EARLIER and paths:
        tree = _build(main, paths, cache, load)  # second pass: every *INCLUDE_PATH known from the start
    return tree
```

`src/deckcheck/diagnostics.py`, `Report`:

```python
@dataclass
class Report:
    main: Path
    diagnostics: list[Diagnostic]
    not_checked: list[NotChecked]
    tree: Any = None   # the resolved Tree, kept for the language server (M2)
    index: Any = None  # the Index, kept for hover and navigation (M2c)
```

(add `from typing import Any`; `Any` avoids an import cycle with `includes`/`index`).

`src/deckcheck/rules/__init__.py`:

```python
def check(main: Path, source=None, cache=None) -> Report:
    tree = resolve_tree(main, source, cache)
    ix = build(tree)
    found = [d for rule in RULES for d in rule(tree, ix)]
    found.sort(key=lambda d: (str(d.path), d.line, d.start, d.code))
    return Report(main, found, not_checked(tree, ix), tree, ix)
```

- [ ] **Step 4: Run new tests, full suite, corpus parity**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py tests/test_includes.py -v` → PASS.
Run: `.venv/Scripts/python -m pytest -q -m "not install"` → all pass, including `test_light_walk_finds_the_same_files_on_the_corpus` for tier 1, VIVA+ and the Yaris.

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck tests/test_rules.py tests/test_includes.py tests/test_index_corpus.py
git commit -m "M2a T2: resolver takes source, cache and reader; include-only light walk; Report keeps tree and index"
```

---

### Task 3: Dependencies and the LSP conversion

**Files:**
- Modify: `pyproject.toml`
- Create: `src/deckcheck/lsp/__init__.py`, `src/deckcheck/lsp/convert.py`
- Test: `tests/test_lsp_convert.py`

**Interfaces:**
- Consumes: `Report` with `.tree` (Task 2).
- Produces:
  - `utf16_column(line: str, col: int, from_disk: bool) -> int`
  - `to_lsp(report: Report, synced: Callable[[Path], bool]) -> dict[str, list[types.Diagnostic]]` — uri → diagnostics for every file of the model, empty lists included.
  - `merge(per_model: dict[str, dict[str, list[types.Diagnostic]]], names: dict[str, str]) -> dict[str, list[types.Diagnostic]]` — `per_model[model_key][uri]`; `names[model_key]` is the main deck's file name.

- [ ] **Step 1: Dependencies**

`pyproject.toml`:

```toml
[project.optional-dependencies]
bakeoff = ["dynars==1.1.0", "psutil>=5.9"]
lsp = ["pygls==2.1.1"]
dev = ["pytest>=8", "pytest-lsp==1.0.1"]
```

and in `[tool.pytest.ini_options]` add `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`, and the marker `"stress: generated heavy decks; run with DECKCHECK_STRESS=1"`.

Run: `.venv/Scripts/python -m pip install -e ".[lsp,dev,bakeoff]"`
Expected: installs pygls 2.1.1, lsprotocol, pytest-lsp, pytest-asyncio.

- [ ] **Step 2: Write the failing tests** (`tests/test_lsp_convert.py`)

```python
from pathlib import Path

from lsprotocol import types
from pygls.uris import from_fs_path

from deckcheck.lsp.convert import merge, to_lsp, utf16_column
from deckcheck.rules import check

TORTURE = Path(__file__).parent / "torture"


def test_ascii_column_unchanged():
    assert utf16_column("         1        99", 10, from_disk=True) == 10


def test_utf8_prefix_shifts_column():
    disk = "é,1,99".encode("utf-8").decode("latin-1")  # how M1 sees a UTF-8 file: 'Ã©,1,99'
    assert utf16_column(disk, 5, from_disk=True) == 4  # VS Code shows 'é' as one character


def test_invalid_utf8_counts_one_per_byte():
    assert utf16_column("\xe9,1,99", 3, from_disk=True) == 3  # shown as U+FFFD, one unit


def test_editor_text_counts_utf16_units():
    assert utf16_column("\U0001F600 1", 2, from_disk=False) == 3  # an emoji is two UTF-16 units


def test_to_lsp_covers_every_file_and_maps_fields():
    r = check(TORTURE / "seeded_mistakes" / "main.k")
    out = to_lsp(r, synced=lambda p: False)
    uris = {from_fs_path(str(f.path)) for f in r.tree.files}
    assert set(out) == uris
    main = out[from_fs_path(str(r.tree.files[0].path))]
    dc001 = next(d for d in main if d.code == "DC001")
    m1 = next(d for d in r.diagnostics if d.code == "DC001")
    assert dc001.range.start == types.Position(m1.line - 1, m1.start)
    assert dc001.severity == types.DiagnosticSeverity.Error and dc001.source == "deckcheck"


def _d(msg):
    return types.Diagnostic(range=types.Range(types.Position(0, 0), types.Position(0, 1)), message=msg)


def test_merge_dedupes_and_names_models():
    per_model = {"a": {"u": [_d("same"), _d("only a")]}, "b": {"u": [_d("same")]}}
    got = merge(per_model, {"a": "case_a.k", "b": "case_b.k"})["u"]
    assert [d.message for d in got] == ["same", "only a (in model case_a.k)"]
```

- [ ] **Step 3: Run, expect failure**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_convert.py -v`
Expected: FAIL (`No module named 'deckcheck.lsp'`).

- [ ] **Step 4: Implement**

`src/deckcheck/lsp/__init__.py`:

```python
"""deckcheck's language server (M2, spec docs/specs/2026-10-30-m2-vscode-design.md). Needs the [lsp] extra."""
```

`src/deckcheck/lsp/convert.py`:

```python
"""M1 diagnostics as LSP diagnostics (M2 spec §5.1). M1 columns count characters of the text it read; the editor
counts UTF-16 units of the text it shows. M1 decodes a file from disk as Latin-1 (one character per byte) while
VS Code decodes UTF-8 with replacement, so a disk column is mapped through that decoding; text from the editor
needs only the UTF-16 count."""
from collections.abc import Callable
from pathlib import Path

from lsprotocol import types
from pygls.uris import from_fs_path

from deckcheck.diagnostics import Report

SEVERITY = {"error": types.DiagnosticSeverity.Error, "warning": types.DiagnosticSeverity.Warning}


def utf16_column(line: str, col: int, from_disk: bool) -> int:
    prefix = line[:col]
    if from_disk:
        prefix = prefix.encode("latin-1").decode("utf-8", errors="replace")
    return len(prefix.encode("utf-16-le")) // 2


def _lines(source) -> dict[int, str]:
    out = {}
    for b in source.blocks:
        out[b.line] = b.text
        for c in b.cards:
            out[c.line] = c.text
    return out


def _uri(path: Path) -> str:
    return from_fs_path(str(path))


def to_lsp(report: Report, synced: Callable[[Path], bool]) -> dict[str, list[types.Diagnostic]]:
    files = {_uri(f.path): f for f in report.tree.files}
    out: dict[str, list[types.Diagnostic]] = {u: [] for u in files}
    texts: dict[str, dict[int, str]] = {}
    for d in report.diagnostics:
        uri = _uri(d.path)
        node = files.get(uri)
        if node is not None and uri not in texts:
            texts[uri] = _lines(node.source)
        line = texts.get(uri, {}).get(d.line)
        disk = node is None or not synced(node.path)
        start, end = ((utf16_column(line, d.start, disk), utf16_column(line, d.end, disk)) if line is not None
                      else (d.start, d.end))
        related = [types.DiagnosticRelatedInformation(
            location=types.Location(_uri(x.path), types.Range(types.Position(x.line - 1, 0), types.Position(x.line - 1, 0))),
            message=x.message) for x in d.related]
        out.setdefault(uri, []).append(types.Diagnostic(
            range=types.Range(types.Position(d.line - 1, start), types.Position(d.line - 1, end)),
            message=d.message, severity=SEVERITY[d.severity], code=d.code, source="deckcheck",
            related_information=related or None))
    return out


def _sig(d: types.Diagnostic) -> tuple:
    r = d.range
    return (r.start.line, r.start.character, r.end.line, r.end.character, d.code, d.severity, d.message)


def merge(per_model: dict[str, dict[str, list[types.Diagnostic]]],
          names: dict[str, str]) -> dict[str, list[types.Diagnostic]]:
    """A file in several models: a finding in all of them is shown once; one in only some names those models."""
    out: dict[str, list[types.Diagnostic]] = {}
    for uri in {u for by_uri in per_model.values() for u in by_uri}:
        models = [m for m, by_uri in per_model.items() if uri in by_uri]
        seen: dict[tuple, list[str]] = {}
        first: dict[tuple, types.Diagnostic] = {}
        for m in models:
            for d in per_model[m][uri]:
                seen.setdefault(_sig(d), []).append(m)
                first.setdefault(_sig(d), d)
        merged = []
        for sig, ms in seen.items():
            d = first[sig]
            if len(models) > 1 and len(set(ms)) < len(models):
                d = types.Diagnostic(range=d.range, message=f"{d.message} (in model {', '.join(names[m] for m in ms)})",
                                     severity=d.severity, code=d.code, source=d.source,
                                     related_information=d.related_information)
            merged.append(d)
        out[uri] = merged
    return out
```

- [ ] **Step 5: Run, expect pass; then commit**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_convert.py -v` → PASS.

```bash
git add pyproject.toml src/deckcheck/lsp tests/test_lsp_convert.py
git commit -m "M2a T3: [lsp] extra; M1 diagnostics to LSP with UTF-16 columns; merge across models"
```

---

### Task 4: Workspace — settings, overlay, main-deck detection, caches

**Files:**
- Create: `src/deckcheck/lsp/workspace.py`
- Test: `tests/test_lsp_workspace.py`

**Interfaces:**
- Consumes: `resolve_tree(..., reader=read_includes)`, `includes._key`, `includes._norm` (Task 2).
- Produces:
  - `Settings` dataclass: `main_decks: list[Path]`, `exclude: list[str]`, `live_threshold: float = 2.0`, `memory_mb: int = 2048`, `ignore: frozenset[str]`; `Settings.from_options(opts: dict, folder: Path) -> Settings`.
  - `Workspace(folders: list[Path], settings: Settings)` with `open(path, text)`, `change(path, text)`, `close(path)`, `source(path) -> str | None`, `synced(path) -> bool`, `scan()`, `ensure_scanned()`, `mark_dirty()`, `models_for(path) -> list[Path]`, `cache_for(main) -> dict`, `drop_file(path)`, `open_models() -> set[str]`, `release_closed()`.

- [ ] **Step 1: Write the failing tests** (`tests/test_lsp_workspace.py`)

```python
from pathlib import Path

from deckcheck.includes import _key, _norm
from deckcheck.lsp.workspace import Settings, Workspace

PART = "*KEYWORD\n*PART\np\n         1         1         1\n*END\n"
MAT = "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n"


def _write(folder: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="latin-1")


def _ws(folder, **opts):
    ws = Workspace([folder], Settings.from_options(opts, folder))
    ws.scan()
    return ws


def test_include_opened_alone_belongs_to_its_main(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n", "mat.k": MAT, "part.k": PART})
    assert _ws(tmp_path).models_for(tmp_path / "part.k") == [_norm(tmp_path / "main.k")]


def test_file_in_two_models(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n",
                      "mat.k": MAT})
    assert sorted(_ws(tmp_path).models_for(tmp_path / "mat.k")) == [_norm(tmp_path / "a.k"), _norm(tmp_path / "b.k")]


def test_unincluded_file_is_its_own_main(tmp_path):
    _write(tmp_path, {"solo.k": PART})
    assert _ws(tmp_path).models_for(tmp_path / "solo.k") == [_norm(tmp_path / "solo.k")]


def test_cycle_leaves_each_file_its_own_main(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nb.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\na.k\n*END\n"})
    assert _ws(tmp_path).models_for(tmp_path / "a.k") == [_norm(tmp_path / "a.k")]


def test_include_path_is_followed(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE_PATH\nlib\n*INCLUDE\nmat.k\n*END\n", "lib/mat.k": MAT})
    assert _ws(tmp_path).models_for(tmp_path / "lib" / "mat.k") == [_norm(tmp_path / "main.k")]


def test_main_decks_setting_overrides_detection(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n",
                      "mat.k": MAT})
    ws = _ws(tmp_path, mainDecks=["b.k"])
    assert ws.models_for(tmp_path / "mat.k") == [_norm(tmp_path / "b.k")]


def test_exclude_glob_is_not_scanned(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    ws = _ws(tmp_path, exclude=["main.k"])
    assert ws.models_for(tmp_path / "mat.k") == [_norm(tmp_path / "mat.k")]


def test_overlay_is_the_source_while_open(tmp_path):
    _write(tmp_path, {"mat.k": MAT})
    ws = _ws(tmp_path)
    ws.open(tmp_path / "mat.k", "edited")
    assert ws.source(_norm(tmp_path / "mat.k")) == "edited" and ws.synced(tmp_path / "mat.k")


def test_close_drops_overlay_and_cache(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    ws = _ws(tmp_path)
    main = _norm(tmp_path / "main.k")
    ws.open(tmp_path / "mat.k", "edited")
    ws.cache_for(main)[_key(_norm(tmp_path / "mat.k"))] = object()
    ws.close(tmp_path / "mat.k")
    assert ws.source(_norm(tmp_path / "mat.k")) is None
    assert _key(_norm(tmp_path / "mat.k")) not in ws.cache_for(main)


def test_change_drops_that_file_from_every_cache(tmp_path):
    _write(tmp_path, {"a.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "b.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n",
                      "mat.k": MAT})
    ws = _ws(tmp_path)
    k = _key(_norm(tmp_path / "mat.k"))
    for main in ("a.k", "b.k"):
        ws.cache_for(_norm(tmp_path / main))[k] = object()
    ws.open(tmp_path / "mat.k", MAT)
    ws.change(tmp_path / "mat.k", MAT + "$ edit\n")
    assert all(k not in ws.cache_for(_norm(tmp_path / m)) for m in ("a.k", "b.k"))


def test_unreadable_file_does_not_stop_the_scan(tmp_path):
    _write(tmp_path, {"main.k": "*KEYWORD\n*INCLUDE\nmat.k\n*END\n", "mat.k": MAT})
    (tmp_path / "junk.k").write_bytes(bytes(range(256)) * 4096)
    assert _ws(tmp_path).models_for(tmp_path / "mat.k") == [_norm(tmp_path / "main.k")]
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_workspace.py -v`
Expected: FAIL (`No module named 'deckcheck.lsp.workspace'`).

- [ ] **Step 3: Implement** `src/deckcheck/lsp/workspace.py`

```python
"""What the server knows about the workspace (M2 spec §4.2, §4.4): the editor's unsaved text, which main decks
each file belongs to, and parsed files kept per model between checks. Detection uses the light include walk:
M1b's location rules, reading only *INCLUDE* blocks."""
import fnmatch
import threading
from dataclasses import dataclass, field
from pathlib import Path

from deckcheck.includes import _key, _norm, resolve_tree
from deckcheck.reader import SourceFile, read_includes

DECK_SUFFIXES = (".k", ".key", ".dyn")


@dataclass
class Settings:
    main_decks: list[Path] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    live_threshold: float = 2.0
    memory_mb: int = 2048
    ignore: frozenset[str] = frozenset()

    @classmethod
    def from_options(cls, opts: dict, folder: Path) -> "Settings":
        return cls(main_decks=[_norm(folder / m) for m in opts.get("mainDecks", [])],
                   exclude=list(opts.get("exclude", [])),
                   live_threshold=float(opts.get("liveThresholdSeconds", 2.0)),
                   memory_mb=int(opts.get("memoryMB", 2048)),
                   ignore=frozenset(c.upper() for c in opts.get("ignore", [])))


class Workspace:
    def __init__(self, folders: list[Path], settings: Settings):
        self.folders = [_norm(f) for f in folders]
        self.settings = settings
        self._overlay: dict[str, str] = {}
        self._reach: dict[str, set[str]] = {}   # main key -> keys of every file its include tree reaches
        self._mains: dict[str, Path] = {}
        self._caches: dict[str, dict[str, SourceFile]] = {}
        self._dirty = True
        self._lock = threading.Lock()

    # the editor's text
    def open(self, path: Path, text: str) -> None:
        self.change(path, text)

    def change(self, path: Path, text: str) -> None:
        with self._lock:
            self._overlay[_key(_norm(path))] = text
        self.drop_file(path)

    def close(self, path: Path) -> None:
        with self._lock:
            self._overlay.pop(_key(_norm(path)), None)
        self.drop_file(path)

    def source(self, path: Path) -> str | None:
        return self._overlay.get(_key(_norm(path)))

    def synced(self, path: Path) -> bool:
        return _key(_norm(path)) in self._overlay

    # parsed files
    def cache_for(self, main: Path) -> dict[str, SourceFile]:
        return self._caches.setdefault(_key(_norm(main)), {})

    def drop_file(self, path: Path) -> None:
        k = _key(_norm(path))
        for cache in self._caches.values():
            cache.pop(k, None)

    def open_models(self) -> set[str]:
        open_files = set(self._overlay)
        return {m for m in self._caches if self._reach.get(m, {m}) & open_files}

    def release_closed(self) -> None:
        """Drop the parse caches of models with no open file (M2 spec §6)."""
        keep = self.open_models()
        for m in list(self._caches):
            if m not in keep:
                del self._caches[m]

    # main decks
    def mark_dirty(self) -> None:
        self._dirty = True

    def ensure_scanned(self) -> None:
        if self._dirty:
            self.scan()

    def _excluded(self, path: Path) -> bool:
        for folder in self.folders:
            try:
                rel = path.relative_to(folder).as_posix()
            except ValueError:
                continue
            if any(fnmatch.fnmatch(rel, g) for g in self.settings.exclude):
                return True
        return False

    def _decks(self) -> list[Path]:
        out = []
        for folder in self.folders:
            for p in folder.rglob("*"):
                if p.suffix.lower() in DECK_SUFFIXES and p.is_file() and not self._excluded(p):
                    out.append(_norm(p))
        return sorted(out)

    def scan(self) -> None:
        light: dict[str, SourceFile] = {}
        reach: dict[str, set[str]] = {}
        mains: dict[str, Path] = {}
        candidates = self.settings.main_decks or self._decks()
        for deck in candidates:
            try:
                tree = resolve_tree(deck, source=self.source, cache=light, reader=read_includes)
            except (OSError, ValueError):
                continue
            reach[_key(deck)] = {_key(f.path) for f in tree.files}
            mains[_key(deck)] = deck
        if not self.settings.main_decks:
            included = set().union(*(r - {k} for k, r in reach.items())) if reach else set()
            mains = {k: p for k, p in mains.items() if k not in included}
        with self._lock:
            self._reach = {k: reach[k] for k in mains}
            self._mains = mains
            self._dirty = False

    def models_for(self, path: Path) -> list[Path]:
        k = _key(_norm(path))
        found = sorted((p for m, p in self._mains.items() if k in self._reach[m]), key=str)
        return found or [_norm(path)]
```

- [ ] **Step 4: Run, expect pass**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_workspace.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck/lsp/workspace.py tests/test_lsp_workspace.py
git commit -m "M2a T4: workspace: overlay, main-deck detection by light include walk, per-model caches"
```

---

### Task 5: Runner — one check at a time, adaptive

**Files:**
- Create: `src/deckcheck/lsp/runner.py`
- Test: `tests/test_lsp_runner.py`

**Interfaces:**
- Produces: `Runner(models, check, publish, threshold, clock=time.monotonic, debounce=0.3, prepare=lambda: None)`:
  - `models: Callable[[Path], list[Path]]` file → main decks; `check: Callable[[Path], Report]`; `publish: Callable[[Path, Report | None, BaseException | None], None]`; `prepare`: run in the worker before requests are mapped (the workspace scan).
  - `request(file: Path, reason: str) -> None` with reason in `"open" | "change" | "save" | "external"`; thread-safe, never blocks.
  - `live(main: Path) -> bool`; `active: str | None` (key of the active editor's model, served first); `step() -> bool` (one unit of work, for tests); `start()` (daemon thread).

- [ ] **Step 1: Write the failing tests** (`tests/test_lsp_runner.py`)

```python
from pathlib import Path

from deckcheck.lsp.runner import Runner


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _runner(durations=None, models=None):
    clock, ran, published = Clock(), [], []

    def check(main):
        ran.append(main)
        clock.t += (durations or {}).get(main.name, 0.01)
        return f"report {main.name} #{len(ran)}"

    r = Runner(models=models or (lambda f: [f]), check=check,
               publish=lambda main, rep, err: published.append((main.name, rep, err)),
               threshold=2.0, clock=clock)
    return r, clock, ran, published


def test_open_checks_at_once():
    r, _, ran, pub = _runner()
    r.request(Path("a.k"), "open")
    assert r.step() and pub == [("a.k", "report a.k #1", None)]


def test_change_on_a_small_model_waits_for_the_pause():
    r, clock, ran, pub = _runner()
    r.request(Path("a.k"), "open"); r.step()
    r.request(Path("a.k"), "change")
    assert not r.step()          # 300 ms debounce not over
    clock.t += 0.31
    assert r.step() and len(pub) == 2


def test_change_on_a_big_model_waits_for_save():
    r, clock, ran, pub = _runner(durations={"big.k": 63.0})
    r.request(Path("big.k"), "open"); r.step()
    assert not r.live(Path("big.k"))
    r.request(Path("big.k"), "change"); clock.t += 1
    assert not r.step()
    r.request(Path("big.k"), "save")
    assert r.step() and len(pub) == 2


def test_repeated_requests_coalesce():
    r, clock, ran, pub = _runner()
    for _ in range(5):
        r.request(Path("a.k"), "save")
    assert r.step() and not r.step() and len(ran) == 1


def test_result_of_superseded_request_is_discarded():
    r, clock, ran, pub = _runner()
    real = r.check
    def check_then_edit(main):
        rep = real(main)
        r.request(Path("a.k"), "save")   # a newer edit arrives while this check runs
        return rep
    r.check = check_then_edit
    r.request(Path("a.k"), "open")
    r.step()
    assert pub == []                      # the older result is never published
    r.check = real
    r.step()
    assert [p[1] for p in pub] == ["report a.k #2"]


def test_active_model_goes_first():
    r, _, ran, _ = _runner()
    r.request(Path("a.k"), "save"); r.request(Path("b.k"), "save")
    r.active = r.key(Path("b.k"))
    r.step()
    assert ran == [Path("b.k")]


def test_file_request_runs_every_model_of_the_file():
    r, _, ran, _ = _runner(models=lambda f: [Path("a.k"), Path("b.k")])
    r.request(Path("mat.k"), "open")
    r.step(); r.step()
    assert sorted(m.name for m in ran) == ["a.k", "b.k"]


def test_failed_check_is_published_as_an_error():
    r, _, _, pub = _runner()
    def boom(main):
        raise RuntimeError("bad")
    r.check = boom
    r.request(Path("a.k"), "open"); r.step()
    assert pub[0][1] is None and isinstance(pub[0][2], RuntimeError)


def test_prepare_runs_before_mapping():
    order = []
    r = Runner(models=lambda f: order.append("map") or [f], check=lambda m: "r", publish=lambda *a: None,
               threshold=2.0, prepare=lambda: order.append("scan"))
    r.request(Path("a.k"), "open"); r.step()
    assert order == ["scan", "map"]
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_runner.py -v`
Expected: FAIL (`No module named 'deckcheck.lsp.runner'`).

- [ ] **Step 3: Implement** `src/deckcheck/lsp/runner.py`

```python
"""One check at a time across the workspace (M2 spec §6). A model whose last full check took under the threshold
is re-checked a moment after typing pauses; a bigger one only on open, save and outside changes. A request that
arrives while its model is being checked makes that result stale: it is discarded, never published."""
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from deckcheck.includes import _key, _norm


@dataclass
class _Job:
    main: Path
    due: float
    order: int


class Runner:
    def __init__(self, models: Callable[[Path], list[Path]], check: Callable, publish: Callable,
                 threshold: float, clock: Callable[[], float] = time.monotonic, debounce: float = 0.3,
                 prepare: Callable[[], None] = lambda: None):
        self.models, self.check, self.publish, self.prepare = models, check, publish, prepare
        self.threshold, self.clock, self.debounce = threshold, clock, debounce
        self.durations: dict[str, float] = {}
        self.active: str | None = None
        self._incoming: list[tuple[Path, str, float]] = []
        self._pending: dict[str, _Job] = {}
        self._gen: dict[str, int] = {}
        self._order = itertools.count()
        self._cv = threading.Condition()

    @staticmethod
    def key(path: Path) -> str:
        return _key(_norm(path))

    def live(self, main: Path) -> bool:
        took = self.durations.get(self.key(main))
        return took is not None and took < self.threshold

    def request(self, file: Path, reason: str) -> None:
        with self._cv:
            self._incoming.append((file, reason, self.clock()))
            self._cv.notify()

    def _schedule(self, main: Path, reason: str, at: float) -> None:
        if reason == "change" and not self.live(main):
            return
        k = self.key(main)
        self._gen[k] = self._gen.get(k, 0) + 1
        due = at + (self.debounce if reason == "change" else 0.0)
        self._pending[k] = _Job(main, due, next(self._order))

    def _next(self) -> _Job | None:
        now = self.clock()
        due = [(k, j) for k, j in self._pending.items() if j.due <= now]
        if not due:
            return None
        k, job = min(due, key=lambda kj: (kj[0] != self.active, kj[1].order))
        del self._pending[k]
        return job

    def _drain(self) -> None:
        """Map waiting file requests to their models and queue them. Called before choosing a job and again after
        a check, so a request that arrived during the check makes its result stale."""
        with self._cv:
            incoming, self._incoming = self._incoming, []
        if not incoming:
            return
        self.prepare()
        mapped = [(main, reason, at) for file, reason, at in incoming for main in self.models(file)]
        with self._cv:
            for main, reason, at in mapped:
                self._schedule(main, reason, at)

    def step(self) -> bool:
        self._drain()
        with self._cv:
            job = self._next()
            if job is None:
                return False
            k = self.key(job.main)
            gen = self._gen[k]
        start = self.clock()
        try:
            report, error = self.check(job.main), None
        except Exception as e:  # a whole-check failure: published as such (spec §6), never raised into the loop
            report, error = None, e
        took = self.clock() - start
        self._drain()
        with self._cv:
            if error is None:
                self.durations[k] = took
            stale = self._gen[k] != gen
        if not stale:
            self.publish(job.main, report, error)
        return True

    def _wait(self) -> None:
        with self._cv:
            while not self._incoming:
                now = self.clock()
                if any(j.due <= now for j in self._pending.values()):
                    return
                timeout = min((j.due - now for j in self._pending.values()), default=None)
                self._cv.wait(timeout)

    def _loop(self) -> None:
        while True:
            self._wait()
            self.step()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="deckcheck-runner", daemon=True).start()
```

- [ ] **Step 4: Run, expect pass**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_runner.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck/lsp/runner.py tests/test_lsp_runner.py
git commit -m "M2a T5: runner: one check at a time, adaptive live/on-save, stale results discarded"
```

---

### Task 6: Server, priority and memory watchdog

**Files:**
- Create: `src/deckcheck/lsp/server.py`, `src/deckcheck/lsp/__main__.py`
- Test: `tests/test_lsp_server.py`, `tests/test_lsp_main.py`

**Interfaces:**
- Consumes: `Workspace`, `Settings` (Task 4), `Runner` (Task 5), `to_lsp`, `merge` (Task 3), `check(main, source, cache)` (Task 2).
- Produces (the protocol contract M2b's client relies on):
  - `initializationOptions`: `{mainDecks, exclude, liveThresholdSeconds, memoryMB, ignore}`.
  - Standard: `didOpen`, `didChange` (incremental), `didSave`, `didClose`, `workspace/didChangeWatchedFiles`; publishes `textDocument/publishDiagnostics` for every file of a checked model, included files first and the main deck last.
  - Custom notification client → server `deckcheck/check` `{uri}`: check the models of a file the client does not sync (above `maxSyncMB`).
  - Custom notification server → client `deckcheck/status` `{main: uri, state: "ok" | "checks on save" | "check failed" | "save to check", notChecked: [{what, reasons, count}]}`.
  - Custom request `deckcheck/ping` → `{"ok": true}` (health and latency).
  - Process: exit code 75 with `deckcheck: memory budget N MB exceeded; pausing` on stderr when over budget.
  - `deckcheck.lsp.__main__`: `lower_priority()`, `rss_bytes() -> int`, `watch(budget: int, rss=rss_bytes, stop=..., period=0.25, sleep=time.sleep)`.

- [ ] **Step 1: Write the failing protocol tests** (`tests/test_lsp_server.py`)

```python
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from lsprotocol import types
from pygls.uris import from_fs_path
from pytest_lsp import client_capabilities, make_test_lsp_client

from deckcheck.lsp.convert import utf16_column
from deckcheck.rules import check

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))


@asynccontextmanager
async def session(folder: Path, **options):
    client = make_test_lsp_client()
    client.statuses = []
    client.feature("deckcheck/status")(lambda ls, params: ls.statuses.append(params))
    await client.start_io(sys.executable, "-m", "deckcheck.lsp")
    await client.initialize_session(types.InitializeParams(
        capabilities=client_capabilities("visual-studio-code"),
        workspace_folders=[types.WorkspaceFolder(uri=from_fs_path(str(folder)), name="ws")],
        initialization_options=options))
    try:
        yield client
    finally:
        await client.shutdown_session()


def uri(path: Path) -> str:
    return from_fs_path(os.path.abspath(path))


def editor_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")  # what VS Code shows by default


def open_doc(client, path: Path, text: str | None = None, version: int = 1) -> None:
    client.text_document_did_open(types.DidOpenTextDocumentParams(types.TextDocumentItem(
        uri=uri(path), language_id="keyword-deck", version=version,
        text=editor_text(path) if text is None else text)))


async def published(client, target: str, timeout: float = 30.0):
    client.diagnostics.pop(target, None)
    deadline = time.monotonic() + timeout
    while target not in client.diagnostics:
        await asyncio.wait_for(client.wait_for_notification("textDocument/publishDiagnostics"),
                               max(0.01, deadline - time.monotonic()))
    return client.diagnostics[target]


def _expected(main: Path) -> set[tuple]:
    rep = check(main)
    out = set()
    for d in rep.diagnostics:
        raw = d.path.read_bytes().decode("latin-1").split("\n")[d.line - 1].rstrip("\r")
        out.add((uri(d.path), d.line - 1, utf16_column(raw, d.start, True), utf16_column(raw, d.end, True),
                 d.code, d.message))
    return out


def _got(client, uris) -> set[tuple]:
    return {(u, d.range.start.line, d.range.start.character, d.range.end.character, d.code, d.message)
            for u in uris for d in client.diagnostics.get(u, [])}


async def test_parity_with_the_cli_on_every_torture_deck():
    async with session(TORTURE) as client:
        for case in CASES:
            main = TORTURE / case / "main.k"
            open_doc(client, main)
            await published(client, uri(main))
            files = {uri(f.path) for f in check(main).tree.files}
            assert _got(client, files) == _expected(main), case


async def test_unsaved_edit_is_rechecked_within_one_second(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path) as client:
        open_doc(client, deck)
        assert not [d for d in await published(client, uri(deck)) if d.code == "DC001"]
        text = editor_text(deck).replace("plate\n         1         1         1", "plate\n         1         1        99")
        t = time.monotonic()
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri=uri(deck), version=2),
            [types.TextDocumentContentChangeWholeDocument(text=text)]))
        diags = await published(client, uri(deck), timeout=5)
        assert [d for d in diags if d.code == "DC001"] and time.monotonic() - t < 1.0


async def test_big_model_waits_for_save(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path, liveThresholdSeconds=0) as client:
        open_doc(client, deck)
        await published(client, uri(deck))
        assert client.statuses[-1]["state"] == "checks on save"
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri=uri(deck), version=2),
            [types.TextDocumentContentChangeWholeDocument(text=editor_text(deck) + "$ edit\n")]))
        with pytest.raises(asyncio.TimeoutError):
            await published(client, uri(deck), timeout=1.5)
        client.text_document_did_save(types.DidSaveTextDocumentParams(types.TextDocumentIdentifier(uri(deck))))
        await published(client, uri(deck), timeout=5)


MAIN = "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n"
PART = "*KEYWORD\n*PART\np\n         1         1         1\n*SECTION_SHELL\n         1\n*END\n"
MAT = "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n"


def _model(tmp):
    for name, text in {"main.k": MAIN, "part.k": PART, "mat.k": MAT}.items():
        (tmp / name).write_text(text, encoding="latin-1")


async def test_include_opened_alone_has_no_false_dc001(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "part.k")
        diags = await published(client, uri(tmp_path / "main.k"))
        assert not [d for u in client.diagnostics for d in client.diagnostics[u] if d.code == "DC001"]


async def test_unsaved_include_is_checked(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k", text=MAT.replace("         1", "         7", 1))
        await published(client, uri(tmp_path / "main.k"))
        assert [d for d in client.diagnostics[uri(tmp_path / "part.k")] if d.code == "DC001"]


async def test_check_notification_reads_an_unsynced_file_from_disk(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        client.protocol.notify("deckcheck/check", {"uri": uri(tmp_path / "part.k")})
        await published(client, uri(tmp_path / "main.k"))


async def test_failed_check_clears_and_reports(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path) as client:
        open_doc(client, deck)
        await published(client, uri(deck))
        deck.unlink()  # the main deck vanishes: the next whole check fails
        client.text_document_did_save(types.DidSaveTextDocumentParams(types.TextDocumentIdentifier(uri(deck))))
        assert await published(client, uri(deck)) == []
        assert client.statuses[-1]["state"] == "check failed"


async def test_untitled_document_is_not_checked(tmp_path):
    async with session(tmp_path) as client:
        client.text_document_did_open(types.DidOpenTextDocumentParams(types.TextDocumentItem(
            uri="untitled:Untitled-1", language_id="keyword-deck", version=1, text="*KEYWORD\n")))
        await asyncio.sleep(0.5)
        assert client.statuses and client.statuses[-1]["state"] == "save to check"


async def test_ping_answers(tmp_path):
    async with session(tmp_path) as client:
        assert (await client.protocol.send_request_async("deckcheck/ping", {}))["ok"] is True
```

`tests/test_lsp_main.py`:

```python
import json
import subprocess
import sys

import pytest

from deckcheck.lsp.__main__ import watch


def test_watch_stops_over_budget():
    calls = []
    watch(100, rss=iter([50, 80, 150]).__next__, stop=lambda: calls.append("stop"), sleep=lambda s: None)
    assert calls == ["stop"]


def _frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def test_server_exits_75_over_budget():
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}, "initializationOptions": {"memoryMB": 1}}}
    proc = subprocess.Popen([sys.executable, "-m", "deckcheck.lsp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.write(_frame(init)); proc.stdin.flush()
    assert proc.wait(timeout=30) == 75
    assert b"memory budget 1 MB exceeded" in proc.stderr.read()


def test_priority_is_below_normal():
    psutil = pytest.importorskip("psutil")
    code = ("from deckcheck.lsp.__main__ import lower_priority; lower_priority(); "
            "import psutil; print(psutil.Process().nice())")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    want = psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 10
    assert int(out) == int(want)
```

- [ ] **Step 2: Run, expect failure**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_server.py tests/test_lsp_main.py -v`
Expected: FAIL (`No module named deckcheck.lsp.__main__` / server process exits immediately).

- [ ] **Step 3: Implement** `src/deckcheck/lsp/__main__.py`

```python
"""Start the language server (M2 spec §3): below-normal CPU priority, and a watchdog that stops the process with
exit code 75 when its memory passes the budget, so the client pauses deckcheck instead of restarting it."""
import os
import sys
import threading
import time

PAUSE = 75


def lower_priority() -> None:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    else:
        os.nice(10)


def rss_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(pmc)
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.WorkingSetSize
    if sys.platform.startswith("linux"):
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS


def watch(budget: int, rss=rss_bytes, stop=None, period: float = 0.25, sleep=time.sleep) -> None:
    while True:
        if rss() > budget:
            (stop or (lambda: os._exit(PAUSE)))()
            return
        sleep(period)


def start_watchdog(budget_mb: int) -> None:
    def stop():
        sys.stderr.write(f"deckcheck: memory budget {budget_mb} MB exceeded; pausing\n")
        sys.stderr.flush()
        os._exit(PAUSE)
    threading.Thread(target=watch, args=(budget_mb * 2**20,), kwargs={"stop": stop}, daemon=True,
                     name="deckcheck-memory").start()


def main() -> None:
    lower_priority()
    from deckcheck.lsp.server import server
    server.start_io()


if __name__ == "__main__":
    main()
```

`src/deckcheck/lsp/server.py`:

```python
"""Protocol handlers (M2 spec §4.2). Each handler records what changed and asks the runner; none waits for a check
(spec §3). Results are published from the runner's thread through the event loop."""
import asyncio
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import from_fs_path, to_fs_path

from deckcheck import __version__
from deckcheck.includes import _key, _norm
from deckcheck.lsp.__main__ import start_watchdog
from deckcheck.lsp.convert import merge, to_lsp
from deckcheck.lsp.runner import Runner
from deckcheck.lsp.workspace import Settings, Workspace
from deckcheck.rules import check


class DeckServer(LanguageServer):
    ws: Workspace
    runner: Runner
    loop: asyncio.AbstractEventLoop
    results: dict[str, dict[str, list[types.Diagnostic]]]
    names: dict[str, str]


server = DeckServer("deckcheck", __version__)


def _path(uri: str) -> Path | None:
    p = to_fs_path(uri)
    return _norm(Path(p)) if p else None


def _status(ls: DeckServer, main: Path, state: str, report=None) -> None:
    items = [{"what": n.what, "reasons": list(n.reasons), "count": n.count} for n in (report.not_checked if report else [])]
    ls.protocol.notify("deckcheck/status", {"main": from_fs_path(str(main)), "state": state, "notChecked": items})


def _publish(ls: DeckServer, main: Path, report, error) -> None:
    k = _key(main)
    previous = set(ls.results.get(k, {}))
    if error is not None or report is None:
        ls.results[k] = {u: [] for u in previous}
        state = "check failed"
        ls.window_log_message(types.LogMessageParams(types.MessageType.Error, f"deckcheck: {main}: {error!r}"))
    else:
        report.diagnostics[:] = [d for d in report.diagnostics if d.code not in ls.ws.settings.ignore]
        ls.results[k] = to_lsp(report, ls.ws.synced)
        for u in previous - set(ls.results[k]):
            ls.results[k][u] = []
        state = "ok" if ls.runner.live(main) else "checks on save"
    ls.names[k] = main.name
    merged = merge(ls.results, ls.names)
    main_uri = from_fs_path(str(main))
    for u in sorted(ls.results[k], key=lambda u: u == main_uri):  # included files first, the main deck last
        ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=u, diagnostics=merged.get(u, [])))
    _status(ls, main, state, report)
    ls.ws.release_closed()


def _check(ls: DeckServer, main: Path):
    return check(main, source=ls.ws.source, cache=ls.ws.cache_for(main))


@server.feature(types.INITIALIZE)
def initialize(ls: DeckServer, params: types.InitializeParams) -> None:
    opts = params.initialization_options or {}
    folders = [Path(to_fs_path(f.uri)) for f in (params.workspace_folders or [])]
    if not folders and params.root_uri:
        folders = [Path(to_fs_path(params.root_uri))]
    settings = Settings.from_options(opts, folders[0] if folders else Path.cwd())
    start_watchdog(settings.memory_mb)
    ls.loop = asyncio.get_running_loop()
    ls.ws = Workspace(folders, settings)
    ls.results, ls.names = {}, {}
    ls.runner = Runner(models=ls.ws.models_for, check=lambda m: _check(ls, m),
                       publish=lambda m, r, e: ls.loop.call_soon_threadsafe(_publish, ls, m, r, e),
                       threshold=settings.live_threshold, prepare=ls.ws.ensure_scanned)
    ls.runner.start()


def _request(ls: DeckServer, uri: str, reason: str) -> None:
    path = _path(uri)
    if path is None:
        ls.protocol.notify("deckcheck/status", {"main": uri, "state": "save to check", "notChecked": []})
        return
    ls.runner.request(path, reason)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: DeckServer, params: types.DidOpenTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is not None:
        ls.ws.open(path, params.text_document.text)
    _request(ls, params.text_document.uri, "open")


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: DeckServer, params: types.DidChangeTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is None:
        return
    ls.ws.change(path, ls.workspace.get_text_document(params.text_document.uri).source)
    _request(ls, params.text_document.uri, "change")


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: DeckServer, params: types.DidSaveTextDocumentParams) -> None:
    ls.ws.mark_dirty()  # includes may have changed: re-detect main decks before the next check
    _request(ls, params.text_document.uri, "save")


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: DeckServer, params: types.DidCloseTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is not None:
        ls.ws.close(path)
        ls.runner.request(path, "external")  # the disk version applies again


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def watched(ls: DeckServer, params: types.DidChangeWatchedFilesParams) -> None:
    ls.ws.mark_dirty()
    for change in params.changes:
        path = _path(change.uri)
        if path is not None:
            ls.ws.drop_file(path)
            ls.runner.request(path, "external")


@server.feature("deckcheck/check")
def check_file(ls: DeckServer, params) -> None:
    # a custom method's params arrive as pygls' generic object, or a dict in some versions
    _request(ls, params["uri"] if isinstance(params, dict) else params.uri, "save")


@server.feature("deckcheck/ping")
def ping(ls: DeckServer, params) -> dict:
    return {"ok": True}
```

`deckcheck/__init__.py` exports `__version__` ("0.1.0").

- [ ] **Step 4: Run, expect pass; full suite**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_server.py tests/test_lsp_main.py -v` → PASS.
Run: `.venv/Scripts/python -m pytest -q -m "not install"` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck/lsp/server.py src/deckcheck/lsp/__main__.py tests/test_lsp_server.py tests/test_lsp_main.py
git commit -m "M2a T6: language server: overlay-aware checks, merged diagnostics, status, ping; low priority, memory watchdog"
```

---

### Task 7: Real decks, harm gate (server side), report

**Files:**
- Create: `tests/test_lsp_stress.py`
- Create: `docs/m2a-server-squiggles.md`
- Modify: `docs/specs/2026-10-30-m2-vscode-design.md` (status line; §5.1 column note; protocol additions)

**Interfaces:**
- Consumes: the protocol contract of Task 6; `session`, `open_doc`, `published`, `uri` from `tests/test_lsp_server.py`.

- [ ] **Step 1: Write the tests** (`tests/test_lsp_stress.py`)

```python
import asyncio
import os
import random
import sys
import time
from pathlib import Path

import pytest

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST
from tests.test_lsp_server import open_doc, published, session, uri

STRESS = pytest.mark.skipif(os.environ.get("DECKCHECK_STRESS") != "1", reason="set DECKCHECK_STRESS=1")


def _entry(name):
    return next(e for e in load_manifest(MANIFEST) if e.name.startswith(name))


async def _ping_ms(client) -> float:
    t = time.monotonic()
    await client.protocol.send_request_async("deckcheck/ping", {})
    return (time.monotonic() - t) * 1000


@pytest.mark.corpus
@pytest.mark.parametrize("name, include, up", [("vivaplus", "vivaplus-joints.k", 1),  # in model/common
                                               ("ccsa-yaris", "set-yaris-detailed-v2j.key", 0)])
async def test_real_include_opened_without_false_errors(name, include, up):
    from deckcheck.includes import resolve_tree
    main = Path(os.path.abspath(fetch(_entry(name))))
    target = next(f.path for f in resolve_tree(main).files if f.path.name == include)
    async with session(main.parents[up]) as client:
        open_doc(client, target)
        await published(client, uri(main), timeout=600)
        assert not [d for u in client.diagnostics for d in client.diagnostics[u] if d.code == "DC001"]
        assert await _ping_ms(client) < 100


@pytest.mark.corpus
async def test_ping_stays_fast_during_a_yaris_check():
    main = fetch(_entry("ccsa-yaris"))
    async with session(main.parent) as client:
        client.protocol.notify("deckcheck/check", {"uri": uri(main)})
        await asyncio.sleep(5)  # the check is running
        worst = max([await _ping_ms(client) for _ in range(20)])
        assert worst < 100, worst


async def _ends_well(client, target: Path, timeout=600):
    """The harm rule: either deckcheck answers, or the server paused itself (exit 75); never a hang or a crash."""
    try:
        await published(client, uri(target), timeout=timeout)
        assert await _ping_ms(client) < 100
        return "checked"
    except Exception:
        code = await asyncio.wait_for(client._server.wait(), 10)
        assert code == 75, code
        return "paused"


@STRESS
@pytest.mark.corpus
async def test_four_occupants_check_or_pause(tmp_path):
    viva = fetch(_entry("vivaplus"))
    cards = []
    for i in range(4):
        off = f"{(i + 1) * 10_000_000:>10}"
        cards += ["*INCLUDE_TRANSFORM", str(viva), off * 7, off * 3, "         0"]
    main = tmp_path / "four.k"
    main.write_text("*KEYWORD\n" + "\n".join(cards) + "\n*END\n", encoding="latin-1")
    async with session(tmp_path) as client:
        open_doc(client, main)
        print("four occupants:", await _ends_well(client, main))


@STRESS
async def test_huge_unsynced_mesh_checks_or_pauses(tmp_path):
    deck = tmp_path / "mesh.k"
    with open(deck, "w", encoding="latin-1") as f:
        f.write("*KEYWORD\n*NODE\n")
        for n in range(1, 5_500_001):  # about 300 MB
            f.write(f"{n:>8}{n * 0.001:>16.6f}{0.0:>16.6f}{0.0:>16.6f}\n")
        f.write("*END\n")
    async with session(tmp_path) as client:
        client.protocol.notify("deckcheck/check", {"uri": uri(deck)})
        print("huge mesh:", await _ends_well(client, deck))


@STRESS
@pytest.mark.parametrize("kind", ["long_line", "binary", "nul"])
async def test_hostile_files_never_break_the_server(tmp_path, kind):
    deck = tmp_path / "x.k"
    random.seed(7)
    data = {"long_line": b"*KEYWORD\n" + b"1" * 1_000_000 + b"\n*END\n",
            "binary": bytes(random.randrange(256) for _ in range(1_000_000)),
            "nul": b"*KEYWORD\n*PART\np\x00\n\x00\x00\x00         1\n*END\n"}[kind]
    deck.write_bytes(data)
    async with session(tmp_path) as client:
        open_doc(client, deck, text=data.decode("utf-8", errors="replace"))
        assert await _ends_well(client, deck, timeout=60) == "checked"


@STRESS
async def test_include_deleted_and_locked_during_a_check(tmp_path):
    big = tmp_path / "mesh.k"
    with open(big, "w", encoding="latin-1") as f:
        f.write("*KEYWORD\n*NODE\n" + "".join(f"{n:>8}{0.0:>16}{0.0:>16}{0.0:>16}\n" for n in range(1, 300_001)) + "*END\n")
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE\nmesh.k\n*END\n", encoding="latin-1")
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await asyncio.sleep(0.2)
        big.unlink()
        await published(client, uri(tmp_path / "main.k"), timeout=120)
        assert await _ping_ms(client) < 100
        if sys.platform == "win32":
            import msvcrt
            big.write_text("*KEYWORD\n*END\n", encoding="latin-1")
            with open(big, "r+b") as f:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                client.protocol.notify("deckcheck/check", {"uri": uri(tmp_path / "main.k")})
                await published(client, uri(tmp_path / "main.k"), timeout=60)
                assert client.statuses[-1]["state"] in ("ok", "check failed")
                assert await _ping_ms(client) < 100
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@STRESS
async def test_fifty_open_includes_and_a_minute_of_typing(tmp_path):
    from lsprotocol import types
    names = [f"inc{i:02}.k" for i in range(50)]
    (tmp_path / "main.k").write_text("*KEYWORD\n" + "".join(f"*INCLUDE\n{n}\n" for n in names) + "*END\n",
                                     encoding="latin-1")
    for i, n in enumerate(names):
        (tmp_path / n).write_text(f"*KEYWORD\n*PART\np{i}\n{i + 1:>10}         1         1\n*END\n", encoding="latin-1")
    async with session(tmp_path) as client:
        for n in names:
            open_doc(client, tmp_path / n)
        target, text, worst = tmp_path / names[0], (tmp_path / names[0]).read_text(encoding="latin-1"), 0.0
        end = time.monotonic() + 60
        version = 1
        while time.monotonic() < end:
            version += 1
            text += "$"
            client.text_document_did_change(types.DidChangeTextDocumentParams(
                types.VersionedTextDocumentIdentifier(uri=uri(target), version=version),
                [types.TextDocumentContentChangeWholeDocument(text=text)]))
            await asyncio.sleep(0.05)
            if version % 10 == 0:
                worst = max(worst, await _ping_ms(client))
        assert worst < 100, worst
        await published(client, uri(tmp_path / "main.k"), timeout=30)
```

- [ ] **Step 2: Run the corpus tests, then the stress set**

Run: `.venv/Scripts/python -m pytest tests/test_lsp_stress.py -m corpus -v -s`
Expected: PASS for VIVA+ and Yaris includes (zero DC001, ping < 100 ms), and the Yaris ping test.
Run (PowerShell): `$env:DECKCHECK_STRESS=1; .venv/Scripts/python -m pytest tests/test_lsp_stress.py -v -s`
Expected: every stress test ends `checked` or `paused`; record each outcome (printed) in the report.

If a ping exceeds 100 ms during a check, the cause is the worker holding the GIL: lower `sys.setswitchinterval` in `__main__.main()` to 0.001 and re-run; ledger the ruling.

- [ ] **Step 3: Write the report** `docs/m2a-server-squiggles.md`, with these sections and measured numbers filled from Step 2's output:
  1. What M2a delivers (protocol contract from Task 6's Interfaces, verbatim).
  2. Parity: torture decks checked through the protocol vs the CLI (case count, result).
  3. Real decks: VIVA+ and Yaris include opened — time to first diagnostics, DC001 count (0), worst ping.
  4. Harm gate (server side): each stress case with its outcome (`checked` / `paused`) and time.
  5. Rulings and deviations from the spec (from the ledger).
  6. What M2b needs: sync limit middleware sends `deckcheck/check` for unsynced files; exit 75 → pause, no restart; process-tree kill; watched-file registration; status bar from `deckcheck/status`.

- [ ] **Step 4: Amend the spec** `docs/specs/2026-10-30-m2-vscode-design.md`:
  - Status line: `M2a done <date> (docs/m2a-server-squiggles.md)`.
  - §5.1: replace "Columns carry over unchanged: …" with "Columns are converted to UTF-16 units of the text the editor shows: a disk file is mapped through UTF-8 decoding with replacement (VS Code's default), editor text is counted directly (`lsp/convert.py`)."
  - §4.2: add the protocol additions (`deckcheck/check`, `deckcheck/status`, `deckcheck/ping`, exit code 75) as listed in Task 6.

- [ ] **Step 5: Full suite and commit**

Run: `.venv/Scripts/python -m pytest -q -m "not install"` → all pass.

```bash
git add tests/test_lsp_stress.py docs/m2a-server-squiggles.md docs/specs/2026-10-30-m2-vscode-design.md
git commit -m "M2a T7: real-deck and stress harm gate for the server; M2a report; spec amended"
```
