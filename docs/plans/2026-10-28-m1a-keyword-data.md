# M1a: Keyword data from pydyna — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract pydyna's keyword field database into a data file deckcheck ships, resolve deck keyword names
against it, and verify it against every keyword behind M0's seven defects. The output is the data, an overrides
file with evidence, and a report.

**Architecture:**
- A build-time tool, `tools/extract_keyword_data.py`, runs in an isolated venv (`.venv-extract`) with
  `ansys-dyna-core==0.12.1`. It instantiates all 3,171 keyword classes and walks their cards into
  `src/deckcheck/data/keywords.json`.
- deckcheck itself only reads that JSON, through `deckcheck.keywords`, which resolves deck keyword names such as
  `BOUNDARY_SPC_SET_ID` to a data entry plus its options.
- A check script prints what the data says for each M0 defect keyword next to the deck evidence. Verdicts become
  `overrides.toml` entries, each with its evidence.

**Tech Stack:** Python 3.12, stdlib only at runtime (`json`, `tomllib`). Build time: `ansys-dyna-core==0.12.1`
(MIT) in `.venv-extract`. pytest.

**Spec:** `docs/specs/2026-10-27-deckcheck-design.md` (B1′ revision). Sections 2, 4, 9, 11 (first M1 bullet) and
12 bind this plan.

## Global Constraints

- deckcheck has **no runtime dependencies** (spec §9). dynars and psutil live in the `bakeoff` extra;
  `ansys-dyna-core` only in `.venv-extract` via `tools/requirements-extract.txt`.
- `ansys-dyna-core` pinned exactly: `0.12.1`. The JSON records this version.
- pydyna is MIT: its license text ships in `NOTICE` beside the data.
- The reader never interprets keyword meaning on its own; every meaning comes from `keywords.json` or
  `overrides.toml` (spec §2).
- Every override carries evidence: a deck file and line, or an LS-DYNA run.
- No GitHub remote, no PyPI publish.
- Work on branch `m1a`, never directly on `main`.

## Review Focus

1. **Name collisions.** Two classes producing the same keyword name. Expected: extraction fails loudly, never
   silently keeps one. Pinned by `test_keyword_names_are_unique` (Task 2).
2. **Option suffix ambiguity.** `MAT_ELASTIC_TITLE` could be the keyword `MAT_ELASTIC` with option `TITLE`, or a
   separate keyword. Expected: the longest data key wins, and the remainder must consist only of that class's
   options. Pinned by `test_resolve_*` (Task 4).
3. **Format suffixes on the keyword line.** `*MAT_ELASTIC +`, `*PART -`, trailing spaces, lowercase, and a
   keyword line carrying a comment. Expected: they resolve to the same entry, with the format recorded separately.
   Pinned by `test_resolve_strips_format_suffix` (Task 4).
4. **Non-deterministic output.** Dict or set ordering changing the JSON between runs. Expected: a byte-identical
   file from two runs. Pinned by `test_extraction_is_deterministic` (Task 2).
5. **Data size.** A JSON too big to ship comfortably. Expected: the size is measured and recorded; gzip if above
   10 MB. Checked in Task 3, step 2.

---

### Task 1: Dependencies and the extraction environment

**Files:**
- Modify: `pyproject.toml`
- Create: `tools/__init__.py`, `tools/requirements-extract.txt`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: `.venv-extract/Scripts/python.exe` with `ansys-dyna-core==0.12.1`, pytest and editable deckcheck.
  deckcheck declares no runtime dependencies.

- [ ] **Step 1: Branch**

```bash
git checkout -b m1a
```

- [ ] **Step 2: Write the failing test** (append to `tests/test_scaffold.py`)

```python
def test_deckcheck_has_no_runtime_dependencies():
    requires = importlib.metadata.requires("deckcheck") or []
    assert all("extra ==" in r for r in requires), [r for r in requires if "extra ==" not in r]
```

- [ ] **Step 3: Run it to see it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scaffold.py -q -p no:cacheprovider`
Expected: FAIL, listing `dynars==1.1.0`.

- [ ] **Step 4: Move dynars to the bakeoff extra**

In `pyproject.toml` set:

```toml
dependencies = []

[project.optional-dependencies]
bakeoff = ["dynars==1.1.0", "psutil>=5.9"]
dev = ["pytest>=8"]
```

and add `markers = ["lsdyna: needs the local LS-DYNA Student install", "extract: needs .venv-extract (ansys-dyna-core)"]`
in place of the current `markers` line.

Run: `.venv/Scripts/python.exe -m pip install -q -e ".[bakeoff,dev]" && .venv/Scripts/python.exe -m pytest tests/test_scaffold.py -q -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 5: Create the extraction environment**

`tools/__init__.py`: empty file.
`tools/requirements-extract.txt`:

```
ansys-dyna-core==0.12.1
pytest>=8
```

Run:

```bash
py -3.12 -m venv .venv-extract && .venv-extract/Scripts/python.exe -m pip install -q -r tools/requirements-extract.txt && .venv-extract/Scripts/python.exe -m pip install -q -e . && .venv-extract/Scripts/python.exe -c "import ansys.dyna.core, importlib.metadata as m; print(m.version('ansys-dyna-core'))"
```

Expected: `0.12.1`. Add `.venv-extract/` to `.gitignore`.

- [ ] **Step 6: Full suite still green, then commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: 48 passed, 2 xfailed.

```bash
git add pyproject.toml tools/ tests/test_scaffold.py .gitignore
git commit -m "No runtime dependencies; isolated pydyna extraction env"
```

---

### Task 2: The extractor

**Files:**
- Create: `tools/extract_keyword_data.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Produces:
  - `extract_class(cls) -> dict` and `extract_all() -> dict`.
  - CLI: `python -m tools.extract_keyword_data <out.json>`.
  - JSON shape:
    ```json
    {"source": {"package": "ansys-dyna-core", "version": "0.12.1"},
     "keywords": {"BOUNDARY_SPC_SET": {
        "class": "BoundarySpcSet",
        "options": [{"name": "ID", "position": "pre/2", "title_order": 1}],
        "links": {"cid": "DEFINE_COORDINATE_SYSTEM", "nsid": "SET_NODE"},
        "cards": [{"kind": "card", "option": null, "conditional": false,
                   "fields": [{"name": "nsid", "type": "int", "offset": 0, "width": 10}, ...]},
                  {"kind": "card", "option": "ID", "conditional": false, "fields": [...]}]}}}
    ```
  - Card kinds: `card`, `table` (rows repeat), `table_group` (its `cards` repeat together), `series` (a run of
    values: `element_width`, `per_card`, `type`), and `card_set`, `text`, `include` (recorded with `class` only;
    9, 2 and 2 occurrences in 0.12.1).

- [ ] **Step 1: Write the failing tests**

`tests/test_extract.py`:

```python
import json

import pytest

pytest.importorskip("ansys.dyna.core")
pytestmark = pytest.mark.extract

from tools.extract_keyword_data import extract_all  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return extract_all()


def test_source_version_recorded(data):
    assert data["source"] == {"package": "ansys-dyna-core", "version": "0.12.1"}


def test_every_class_extracted(data):
    # 3171 exported names in 0.12.1; distinct classes may be fewer if some are aliases (record the real count).
    assert 3000 <= len(data["keywords"]) <= 3171


def test_keyword_names_are_unique(data):
    classes = [k["class"] for k in data["keywords"].values()]
    assert len(set(classes)) == len(classes)


def test_spc_set_id_option_and_links(data):
    k = data["keywords"]["BOUNDARY_SPC_SET"]
    assert k["options"] == [{"name": "ID", "position": "pre/2", "title_order": 1}]
    assert k["links"] == {"cid": "DEFINE_COORDINATE_SYSTEM", "nsid": "SET_NODE"}
    opt = [c for c in k["cards"] if c["option"] == "ID"][0]
    assert [(f["name"], f["offset"], f["width"]) for f in opt["fields"]] == [("id", 0, 10), ("heading", 10, 70)]
    main = [c for c in k["cards"] if c["option"] is None][0]
    assert main["fields"][0] == {"name": "nsid", "type": "int", "offset": 0, "width": 10}


def test_part_is_a_table_group_heading_then_ids(data):
    k = data["keywords"]["PART"]
    assert k["cards"][0]["kind"] == "table_group"
    sub = k["cards"][0]["cards"]
    assert sub[0]["fields"][0]["name"] == "heading" and sub[1]["fields"][0]["name"] == "pid"
    assert k["links"]["mid"] == "MAT"


def test_part_inertia_present_with_links(data):
    k = data["keywords"]["PART_INERTIA"]
    names = [f["name"] for c in k["cards"] for f in c.get("fields", [])]
    assert "pid" in names and k["links"]["mid"] == "MAT"


def test_conditional_cards_are_flagged(data):
    flags = [c["conditional"] for k in data["keywords"].values() for c in k["cards"]]
    assert any(flags) and not all(flags)


def test_extraction_is_deterministic():
    assert json.dumps(extract_all(), sort_keys=True) == json.dumps(extract_all(), sort_keys=True)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv-extract/Scripts/python.exe -m pytest tests/test_extract.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: tools.extract_keyword_data`.

- [ ] **Step 3: Write the extractor**

`tools/extract_keyword_data.py`:

```python
"""Extract pydyna's keyword field database (ansys-dyna-core, MIT) into deckcheck's keywords.json.

Build-time only: run in .venv-extract. deckcheck never imports pydyna at runtime.
"""
import importlib.metadata
import json
import sys
from pathlib import Path

from ansys.dyna.core import keywords as kw
from ansys.dyna.core.lib.keyword_base import KeywordBase


def _fields(schema) -> list[dict]:
    out = []
    for item in schema:
        if hasattr(item, "offset") and hasattr(item, "width"):
            out.append({"name": item.name, "type": getattr(item.type, "__name__", str(item.type)),
                        "offset": item.offset, "width": item.width})
        elif isinstance(item, tuple):
            out.extend(_fields(item))
    return out


def _card(card, option: str | None) -> dict | list[dict]:
    kind = type(card).__name__
    base = {"option": option, "conditional": getattr(card, "_active_func", None) is not None}
    if kind == "OptionCardSet":
        name = card._option_spec.name
        return [c for sub in card._cards for c in _flat(_card(sub, name))]
    if kind == "Card":
        return {"kind": "card", **base, "fields": _fields(card._schema)}
    if kind == "TableCard":
        return {"kind": "table", **base, "fields": _fields(card._schema)}
    if kind == "TableCardGroup":
        return {"kind": "table_group", **base, "cards": [c for sub in card._cards for c in _flat(_card(sub, option))]}
    if kind == "SeriesCard":
        return {"kind": "series", **base, "name": card._name, "element_width": card._element_width,
                "per_card": card._fields_per_card, "type": getattr(card._type, "__name__", str(card._type))}
    names = {"CardSet": "card_set", "TextCard": "text", "IncludeCard": "include"}
    return {"kind": names.get(kind, "unknown"), **base, "class": kind}


def _flat(x) -> list[dict]:
    return x if isinstance(x, list) else [x]


def _name(cls) -> str:
    sub = cls.subkeyword
    return cls.keyword if not sub or sub == cls.keyword else f"{cls.keyword}_{sub}"


def extract_class(cls) -> dict:
    inst = cls()
    return {"class": cls.__name__,
            "options": [{"name": o.name, "position": o._position, "title_order": o._title_order}
                        for o in getattr(cls, "_option_spec_list", [])],
            "links": {f: t.name for f, t in sorted(getattr(cls, "_link_fields", {}).items())},
            "cards": [c for card in inst._cards for c in _flat(_card(card, None))]}


def extract_all() -> dict:
    # A set: the same class can be exported under more than one name, which is not a collision.
    classes = sorted({getattr(kw, n) for n in dir(kw)
                      if isinstance(getattr(kw, n), type) and issubclass(getattr(kw, n), KeywordBase)
                      and getattr(kw, n) is not KeywordBase}, key=lambda c: c.__name__)
    keywords: dict[str, dict] = {}
    for cls in classes:
        name = _name(cls)
        if name in keywords:
            raise ValueError(f"keyword name collision: {name} from {keywords[name]['class']} and {cls.__name__}")
        keywords[name] = extract_class(cls)
    return {"source": {"package": "ansys-dyna-core", "version": importlib.metadata.version("ansys-dyna-core")},
            "keywords": dict(sorted(keywords.items()))}


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(extract_all(), sort_keys=True, separators=(",", ":")), encoding="utf-8")
```

- [ ] **Step 4: Run the tests**

Run: `.venv-extract/Scripts/python.exe -m pytest tests/test_extract.py -q -p no:cacheprovider`
Expected: 8 passed.
- If `test_keyword_names_are_unique` fails, or `extract_all` raises a collision, that is a Review Focus 1 finding.
  Record both classes in the ledger. Rule on the naming: append the class name only for the colliding pair, and
  test that rule. Do not drop either class.
- If `test_every_class_extracted` is off by a small number for that reason, update the expected count with a
  ruling.

- [ ] **Step 5: Commit**

```bash
git add tools/extract_keyword_data.py tests/test_extract.py
git commit -m "Extract pydyna keyword database into JSON"
```

---

### Task 3: Ship the data and its license

**Files:**
- Create: `src/deckcheck/data/__init__.py`, `src/deckcheck/data/keywords.json`, `NOTICE`
- Create: `src/deckcheck/keywords.py` (loader only in this task)
- Test: `tests/test_keywords.py`

**Interfaces:**
- Produces: `deckcheck.keywords.load() -> dict` (the parsed JSON, cached); `deckcheck.keywords.SOURCE_VERSION`.

- [ ] **Step 1: Write the failing test**

`tests/test_keywords.py`:

```python
from deckcheck import keywords


def test_shipped_data_loads():
    data = keywords.load()
    assert data["source"]["version"] == "0.12.1"
    assert {"PART", "PART_INERTIA", "BOUNDARY_SPC_SET"} <= set(data["keywords"])


def test_load_is_cached():
    assert keywords.load() is keywords.load()
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_keywords.py -q -p no:cacheprovider`
Expected: FAIL (`cannot import name 'keywords'`).

- [ ] **Step 2: Generate the data and measure it**

Run:

```bash
mkdir -p src/deckcheck/data && touch src/deckcheck/data/__init__.py && .venv-extract/Scripts/python.exe -m tools.extract_keyword_data src/deckcheck/data/keywords.json && ls -la src/deckcheck/data/keywords.json
```

Expected: the file exists. Record its size in the commit message. If it is above 10 MB, write it gzipped as
`keywords.json.gz` instead (`gzip.open(..., "wt", encoding="utf-8")` in the CLI), have `load()` read the `.gz`,
and record a ruling.

- [ ] **Step 3: Write the loader**

`src/deckcheck/keywords.py`:

```python
"""Keyword data extracted from pydyna (ansys-dyna-core, MIT; see NOTICE). Read-only at runtime."""
import functools
import json
from importlib import resources


@functools.cache
def load() -> dict:
    return json.loads(resources.files("deckcheck.data").joinpath("keywords.json").read_text(encoding="utf-8"))
```

- [ ] **Step 4: NOTICE**

Run:

```bash
.venv-extract/Scripts/python.exe -c "import importlib.metadata as m; d=m.distribution('ansys-dyna-core'); print([f for f in d.files if 'LICENSE' in f.name.upper()])"
```

Write `NOTICE`:

```
deckcheck ships keyword field data extracted from PyDYNA (ansys-dyna-core 0.12.1),
Copyright (c) ANSYS, Inc. and/or its affiliates, licensed under the MIT License:

<the full text of the LICENSE file listed above, copied verbatim>
```

Include `NOTICE` in the wheel: add `[tool.hatch.build.targets.wheel.force-include]` with `"NOTICE" = "deckcheck/NOTICE"`.

- [ ] **Step 5: Run the tests, then commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_keywords.py tests/test_scaffold.py -q -p no:cacheprovider`
Expected: 5 passed.

```bash
git add src/deckcheck/data src/deckcheck/keywords.py NOTICE pyproject.toml tests/test_keywords.py
git commit -m "Ship extracted keyword data (pydyna 0.12.1, MIT) with NOTICE"
```

---

### Task 4: Resolve deck keyword names

**Files:**
- Modify: `src/deckcheck/keywords.py`
- Test: `tests/test_keywords.py`

**Interfaces:**
- Produces: `resolve(line: str) -> Resolved | None`, where `Resolved` is a frozen dataclass with fields
  `name: str` (the data key), `options: tuple[str, ...]` (in deck order) and `format: str` (`""`, `"+"` long, or
  `"-"` short). `line` is the raw keyword line, including its `*`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_keywords.py`)

```python
from deckcheck.keywords import Resolved, resolve


def test_resolve_plain():
    assert resolve("*PART") == Resolved("PART", (), "")


def test_resolve_option_suffix():
    assert resolve("*BOUNDARY_SPC_SET_ID") == Resolved("BOUNDARY_SPC_SET", ("ID",), "")


def test_resolve_longest_key_wins():
    assert resolve("*PART_INERTIA").name == "PART_INERTIA"


def test_resolve_title_option():
    r = resolve("*DEFINE_TABLE_TITLE")
    assert r.name == "DEFINE_TABLE" and r.options == ("TITLE",)


def test_resolve_strips_format_suffix():
    assert resolve("*MAT_ELASTIC +") == Resolved("MAT_ELASTIC", (), "+")
    assert resolve("*mat_elastic   ") == Resolved("MAT_ELASTIC", (), "")


def test_resolve_ignores_trailing_comment():
    assert resolve("*PART $ bumper parts").name == "PART"


def test_resolve_unknown_is_none():
    assert resolve("*NOT_A_KEYWORD_AT_ALL") is None


def test_resolve_rejects_non_option_remainder():
    # MAT_ELASTIC exists; "_BANANA" is not one of its options, so this is not MAT_ELASTIC.
    assert resolve("*MAT_ELASTIC_BANANA") is None
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_keywords.py -q -p no:cacheprovider`
Expected: FAIL (`cannot import name 'Resolved'`).

- [ ] **Step 2: Implement** (append to `src/deckcheck/keywords.py`)

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Resolved:
    name: str
    options: tuple[str, ...]
    format: str


def _split_options(rest: str, allowed: set[str]) -> tuple[str, ...] | None:
    """Split '_ID_TITLE'-style remainders into known option names, longest match first."""
    out: list[str] = []
    while rest:
        if not rest.startswith("_"):
            return None
        for opt in sorted(allowed, key=len, reverse=True):
            if rest[1:].startswith(opt) and (len(rest) == len(opt) + 1 or rest[len(opt) + 1] == "_"):
                out.append(opt)
                rest = rest[len(opt) + 1:]
                break
        else:
            return None
    return tuple(out)


def resolve(line: str) -> Resolved | None:
    text = line.split("$", 1)[0].strip()
    if not text.startswith("*"):
        return None
    head, _, tail = text[1:].partition(" ")
    fmt = tail.strip() if tail.strip() in ("+", "-") else ""
    if head.endswith(("+", "-")) and not fmt:
        head, fmt = head[:-1], head[-1]
    name = head.upper()
    data = load()["keywords"]
    for cut in range(len(name), 0, -1):
        key = name[:cut]
        if key in data and (cut == len(name) or name[cut] == "_"):
            opts = _split_options(name[cut:], {o["name"] for o in data[key]["options"]})
            if opts is not None:
                return Resolved(key, opts, fmt)
    return None
```

- [ ] **Step 3: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_keywords.py -q -p no:cacheprovider`
Expected: 10 passed.
- If `test_resolve_title_option` fails because pydyna names `DEFINE_TABLE_TITLE` as its own class, the data
  wins. Change the test to the real structure, with a ruling quoting the data entry.
- The same applies to `MAT_ELASTIC_TITLE`-style names. The point of the test is that resolution follows the data,
  not this plan's guess.

- [ ] **Step 4: Commit**

```bash
git add src/deckcheck/keywords.py tests/test_keywords.py
git commit -m "Resolve deck keyword names against the extracted data"
```

---

### Task 5: Coverage of the M0 corpus

**Files:**
- Create: `bakeoff/keyword_coverage.py`
- Create: `bakeoff/results/keyword_coverage.json`

**Interfaces:**
- Consumes: `resolve` (Task 4); `load_manifest`, `fetch` (M0); the torture decks.
- Produces: per deck, keyword occurrences resolved and unresolved, plus the unresolved names with counts.

- [ ] **Step 1: Write the script**

`bakeoff/keyword_coverage.py`:

```python
"""How many keyword lines in the M0 corpus resolve against the extracted data? Follows plain *INCLUDE names
found next to each file (a full include resolver comes in M1b), so coverage is a lower bound."""
import json
import sys
from collections import Counter
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from deckcheck.keywords import resolve


def keyword_lines(root: Path) -> list[str]:
    seen, todo, out = set(), [root], []
    while todo:
        f = todo.pop()
        if f in seen or not f.exists():
            continue
        seen.add(f)
        lines = f.read_bytes().decode("latin-1").splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("*"):
                out.append(ln)
                if ln.upper().startswith("*INCLUDE") and i + 1 < len(lines):
                    nxt = next((x for x in lines[i + 1:i + 4] if x.strip() and not x.startswith("$")), "")
                    todo.append(f.parent / nxt.strip())
    return out


def main(out: Path) -> None:
    decks = [(p.parent.name, p) for p in sorted(Path("tests/torture").glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(Path("tests/corpus/manifest.toml"))]
    report, missing_all = {}, Counter()
    for name, root in decks:
        lines = keyword_lines(root)
        missing = Counter(ln.split("$")[0].strip().upper() for ln in lines if resolve(ln) is None)
        missing_all.update(missing)
        report[name] = {"keyword_lines": len(lines), "unresolved": sum(missing.values())}
    total = sum(r["keyword_lines"] for r in report.values())
    unresolved = sum(r["unresolved"] for r in report.values())
    out.write_text(json.dumps({"total": total, "unresolved": unresolved, "decks": report,
                               "unresolved_names": missing_all.most_common()}, indent=1), encoding="utf-8")
    print(f"{total - unresolved}/{total} keyword lines resolve; top unresolved: {missing_all.most_common(10)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe -m bakeoff.keyword_coverage bakeoff/results/keyword_coverage.json`
Expected: one summary line. Read the top unresolved names. Each is either:
- a real gap in pydyna's data, recorded in Task 7's report; or
- a resolver bug, fixed by TDD in `tests/test_keywords.py` before continuing (a failing test reproducing that line
  first).

`*KEYWORD`, `*END`, `*TITLE` and `*COMMENT` may be legitimately absent from the data. Note them, don't fix them.

- [ ] **Step 3: Commit**

```bash
git add bakeoff/keyword_coverage.py bakeoff/results/keyword_coverage.json
git commit -m "Measure keyword coverage of the M0 corpus"
```

---

### Task 6: Check the data against M0's defect keywords; write overrides

**Files:**
- Create: `bakeoff/check_keyword_data.py`
- Create: `src/deckcheck/data/overrides.toml`
- Modify: `src/deckcheck/keywords.py` (an `overrides()` loader)
- Test: `tests/test_keywords.py`

**Interfaces:**
- Produces:
  - `deckcheck.keywords.overrides() -> dict`, the parsed TOML.
  - Schema: one `[[override]]` per correction, with keys:
    - `keyword` (data key);
    - `field` (or `card` for a whole card);
    - `set` (a table of what changes, e.g. `{link = "SET_PART"}` or `{link_by = "sstyp", map = {"2" = "SET_PART", "3" = "PART"}}`);
    - `evidence` (`"<file>:<line>"` or `"LS-DYNA <torture case>"`);
    - `reason`.

- [ ] **Step 1: Write the check script**

`bakeoff/check_keyword_data.py`:

```python
"""Print what the extracted data says for each keyword behind M0's seven defects, beside the deck evidence."""
from deckcheck.keywords import load

CASES = [
    ("BOUNDARY_SPC_SET", "_ID option card placement (bolts001.key:78-81)"),
    ("CONTACT_DRAWBEAD", "_ID option + set types (cross_member_op10.dyn)"),
    ("CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR", "ssid kind depends on sstyp (bolts001.key:288-291)"),
    ("CONTACT_AUTOMATIC_NODES_TO_SURFACE", "ssid/msid kind depends on sstyp/mstyp"),
    ("ICFD_PART", "defines ICFD part ids (tutorial 9 main_fsi)"),
    ("ICFD_PART_VOL", "references ICFD parts"),
    ("MESH_VOLUME", "references ICFD parts"),
    ("PART_INERTIA", "defines PART (torture part_inertia)"),
    ("PART", "heading then ids; blank heading line (torture blank_title)"),
    ("BOUNDARY_PRESCRIBED_MOTION_RIGID", "pid is a PART, not a NODE (EX09)"),
    ("CONTROL_IMPLICIT_SOLUTION", "arcctl = 0 means off (beam_sub.key:66)"),
    ("DEFINE_TABLE", "series lcid -> DEFINE_CURVE (crashbox.k:153339)"),
    ("AIRBAG_SIMPLE_PRESSURE_VOLUME", "negative cn = curve |cn| (BARRIER_DELAY_20MS.k:38195)"),
    ("INCLUDE_TRANSFORM", "tranid -> DEFINE_TRANSFORMATION (Yaris combine.key:101)"),
    ("RIGIDWALL_PLANAR", "nsid -> SET_NODE (Yaris combine.key:238)"),
    ("INITIAL_VELOCITY_GENERATION", "nsid/pid kind depends on styp (Yaris set-yaris:224)"),
]

data = load()["keywords"]
for name, why in CASES:
    k = data.get(name)
    print(f"\n== {name}: {why}")
    if k is None:
        print("   NOT IN DATA")
        continue
    print("   options:", [(o["name"], o["position"]) for o in k["options"]])
    print("   links:  ", k["links"])
    for c in k["cards"]:
        fields = [f["name"] for f in c.get("fields", [])] or [f["name"] for s in c.get("cards", []) for f in s["fields"]]
        print(f"   {c['kind']:<11} opt={c['option']!s:<6} cond={c['conditional']!s:<5} {fields[:10]}")
```

- [ ] **Step 2: Run it, judge each case**

Run: `.venv/Scripts/python.exe -m bakeoff.check_keyword_data > bakeoff/results/keyword_data_check.txt`

For each of the 16 cases, compare the printout with the deck text at the cited evidence: open the deck file at
that line. Write one row per case into the Task 7 report: data says / deck says / verdict, where the verdict is
**correct** or **override needed**. Do not write an override from memory of the LS-DYNA manual. Evidence is the
deck text or an LS-DYNA run.

- [ ] **Step 3: Write the failing test for overrides** (append to `tests/test_keywords.py`)

```python
from deckcheck.keywords import load, overrides


def test_every_override_names_a_real_keyword_and_has_evidence():
    data = load()["keywords"]
    for o in overrides()["override"]:
        assert o["keyword"] in data, o
        assert o["evidence"] and o["reason"], o
        assert ("field" in o) != ("card" in o), o
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_keywords.py -q -p no:cacheprovider`
Expected: FAIL (`cannot import name 'overrides'`).

- [ ] **Step 4: Implement the loader and write the overrides**

Append to `src/deckcheck/keywords.py`:

```python
import tomllib


@functools.cache
def overrides() -> dict:
    return tomllib.loads(resources.files("deckcheck.data").joinpath("overrides.toml").read_text(encoding="utf-8"))
```

Write `src/deckcheck/data/overrides.toml`:
- one `[[override]]` per "override needed" verdict from step 2, in the schema above;
- the header comment: `# Corrections to the pydyna-extracted keyword data. Every entry cites deck text or an LS-DYNA run.`

Run: `.venv/Scripts/python.exe -m pytest tests/test_keywords.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bakeoff/check_keyword_data.py bakeoff/results/keyword_data_check.txt src/deckcheck/data/overrides.toml src/deckcheck/keywords.py tests/test_keywords.py
git commit -m "Check keyword data against M0 defect keywords; overrides with evidence"
```

---

### Task 7: Report and gate

**Files:**
- Create: `docs/m1a-keyword-data.md`
- Modify: `docs/specs/2026-10-27-deckcheck-design.md` (§12: answer the first open question)

- [ ] **Step 1: Write the report**

`docs/m1a-keyword-data.md` contains:
1. **The data:** keyword count, card-kind counts, conditional-card count, link count by target kind, file size.
2. **Coverage:** keyword lines resolved over total, per tier (from `keyword_coverage.json`), and the top 10
   unresolved names, each with gap / resolver note.
3. **The 16-case check table** (Task 6): data says / deck says / verdict.
4. **Overrides written,** and what they imply for M1b/M1c. In particular:
   - conditional cards: how the field reader must decide whether a conditional card is present;
   - kind-by-field references (`sstyp`, `styp`): handled by `link_by` overrides;
   - which entity kinds have no `LinkType` (ICFD parts): handled by overrides.
5. **Answer to spec §12** "does pydyna's data mark sign-encoded references and `*INCLUDE_TRANSFORM` offsets".

- [ ] **Step 2: Update the spec, run the suite, commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: all pass, 2 xfailed (the M0 dynars defects).

```bash
git add docs/m1a-keyword-data.md docs/specs/2026-10-27-deckcheck-design.md
git commit -m "M1a report: keyword data coverage and verification"
```

- [ ] **Step 3: Gate**

Stop. Present the report to Chintan: the coverage, the overrides, and their implications for M1b (reader and
includes). Do not start the M1b plan until he has read it.
