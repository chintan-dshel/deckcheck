# M0: dynars go/no-go — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether deckcheck can stand on dynars: parse, rule accuracy, line accuracy, round-trip and
format handling across a three-tier deck corpus, ending in a written go/no-go.

**Architecture:** M0 is a measurement project, not product code. A `bakeoff/` package holds three pieces:
- a corpus fetcher that downloads external decks pinned by sha256;
- a probe that measures dynars on one deck, running in a child process;
- a runner that drives the probe under a memory watchdog and writes JSONL.

Hand-written torture decks are checked against real LS-DYNA Student before they count as ground truth. Nothing
here becomes deckcheck's runtime code; the M1 plan is written after this one finishes.

**Tech Stack:** Python 3.12 (`py -3.12`), dynars 1.1.0 (pinned), psutil, pytest, tomllib (stdlib). LS-DYNA
Student R16.1 (already installed) as the validity oracle.

**Spec:** `docs/specs/2026-10-27-deckcheck-design.md` — sections 2, 7, 8, 11 bind this plan.

## Global Constraints

- dynars pinned exactly: `dynars==1.1.0`.
- `requires-python = ">=3.10"`; develop on Python 3.12.
- License: Apache-2.0.
- External decks are never committed. Each is listed in `tests/corpus/manifest.toml` with URL and sha256, and
  cached in `.corpus/` (gitignored).
- Torture decks are committed byte-exact: `.gitattributes` marks `tests/torture/** -text` (this machine's git
  converts LF to CRLF otherwise).
- Memory cap for any single deck run: 4096 MB (dev laptop has 7.7 GB). Timeout: 1800 s per deck.
- Never "LS-DYNA" in a package or project name.
- No GitHub remote, no PyPI publish in M0.
- LS-DYNA Student: `C:\Program Files\LS-DYNA Suite R16.1 Student\lsdyna\ls-dyna_smp_d_R16.1_180-gd50332dbe5_winx64_ifort190_sse2_studentversion.exe`,
  run with environment variable `LSTC_LICENSE=Ansys`.
- Downloaded decks are untrusted data: parse only, never execute; run Python that reads them with `-I` where
  invoked by hand.

## Review Focus

1. **CRLF line endings** (decks from Windows pre-processors). Expected: dynars parses them, round-trip stays
   byte-identical, and line numbers are not doubled. Pinned by torture case `crlf` (Task 2) and its round-trip
   assertion (Task 5).
2. **Non-UTF-8 bytes** (Latin-1 umlauts in titles, common in European models like VIVA+). Expected: parse
   succeeds, no crash on decoding, round-trip is byte-identical. Pinned by torture case `latin1` (Task 2, Task 5).
3. **Windows `\\?\` long-path prefix** in dynars' reported paths. Expected: every path in our results is a plain
   path that `Path.exists()` accepts. Pinned by `test_clean_path_*` (Task 5).
4. **A deck that eats all memory.** Expected: the watchdog kills it at the cap and records an error row; the
   laptop never swaps to death. Pinned by `test_run_one_kills_at_cap` (Task 6).
5. **A large result through a pipe.** Expected: no deadlock when a deck has thousands of findings. Pinned by the
   design choice (probe writes to a file, not stdout) and `test_run_one_large_output` (Task 6).

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `README.md`, `.gitignore`, `.gitattributes`
- Create: `src/deckcheck/__init__.py`, `bakeoff/__init__.py`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: importable `deckcheck` (version string) and `bakeoff` packages; `.venv` with dynars, psutil, pytest.

- [ ] **Step 1: Create the environment**

Run (Git Bash, from `D:\AI_Projects\deckcheck`):
```bash
py -3.12 -m venv .venv
```
Expected: `.venv/Scripts/python.exe` exists.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "deckcheck"
version = "0.0.1"
description = "A linter for LS-DYNA keyword decks"
license = "Apache-2.0"
requires-python = ">=3.10"
dependencies = ["dynars==1.1.0"]

[project.optional-dependencies]
bakeoff = ["psutil>=5.9"]
dev = ["pytest>=8"]

[tool.hatch.build.targets.wheel]
packages = ["src/deckcheck"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = ["lsdyna: needs the local LS-DYNA Student install"]
```

- [ ] **Step 3: Write the small files**

`src/deckcheck/__init__.py`:
```python
"""deckcheck: a linter for LS-DYNA keyword decks."""
__version__ = "0.0.1"
```

`bakeoff/__init__.py`:
```python
"""M0 measurement tooling: is dynars good enough to build deckcheck on?"""
```

`.gitignore`:
```
.venv/
.corpus/
__pycache__/
*.egg-info/
.pytest_cache/
bakeoff/scratch/
```

`.gitattributes`:
```
tests/torture/** -text
```

`README.md`:
```markdown
# deckcheck

A linter for LS-DYNA keyword decks. Early development: see `docs/specs/` for the design.
```

`LICENSE`: the full Apache License 2.0 text. Run:
```bash
curl -s https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE && head -3 LICENSE
```
Expected: the first lines read `Apache License` / `Version 2.0, January 2004`.

- [ ] **Step 4: Write the failing test**

`tests/test_scaffold.py`:
```python
import importlib.metadata


def test_packages_import():
    import bakeoff  # noqa: F401
    import deckcheck
    assert deckcheck.__version__ == "0.0.1"


def test_dynars_is_pinned_version():
    assert importlib.metadata.version("dynars") == "1.1.0"
```

- [ ] **Step 5: Run it to see it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scaffold.py -v`
Expected: FAIL. pytest is not installed yet ("No module named pytest").

- [ ] **Step 6: Install**

Run: `.venv/Scripts/python.exe -m pip install -e ".[bakeoff,dev]"`
Expected: ends with `Successfully installed ... dynars-1.1.0 ... psutil-...`.

- [ ] **Step 7: Run the test to see it pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scaffold.py -v`
Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml LICENSE README.md .gitignore .gitattributes src bakeoff tests/test_scaffold.py
git commit -m "Scaffold deckcheck package and M0 bakeoff tooling"
```

---

### Task 2: Torture decks

Ten tiny, complete models, one quirk each. Each lives in `tests/torture/<case>/` with a root deck `main.k`, any
included files, and an `expected.toml` that states what is true about it. Expected findings are decided from
what the deck says, not from what dynars reports.

**Files:**
- Create: `tests/torture/<case>/main.k` and `expected.toml` for each case below
- Create: `tests/torture/make_byte_cases.py` (writes the `crlf` and `latin1` cases, which need exact bytes)
- Test: `tests/test_torture_layout.py`

**Interfaces:**
- Produces: the case folders. `expected.toml` schema:
  ```toml
  lsdyna_valid = true          # LS-DYNA Student must read it to normal termination (Task 3 checks)
  findings = []                # expected dynars findings, each {rule = "...", line = N}; line = keyword line
  note = "what the quirk is"
  ```

- [ ] **Step 1: Write the layout test**

`tests/test_torture_layout.py`:
```python
import tomllib
from pathlib import Path

TORTURE = Path(__file__).parent / "torture"
CASES = ["base", "free_format", "long_format", "parameter", "include_path", "comments",
         "lowercase", "tabs", "crlf", "latin1", "seeded_mistakes"]


def test_every_case_has_main_and_expected():
    for case in CASES:
        folder = TORTURE / case
        assert (folder / "main.k").is_file(), case
        expected = tomllib.loads((folder / "expected.toml").read_text(encoding="utf-8"))
        assert isinstance(expected["lsdyna_valid"], bool), case
        assert isinstance(expected["findings"], list), case


def test_byte_cases_have_their_bytes():
    assert b"\r\n" in (TORTURE / "crlf" / "main.k").read_bytes()
    assert b"Pr\xfcfplatte" in (TORTURE / "latin1" / "main.k").read_bytes()
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_torture_layout.py -v`
Expected: FAIL on `base` (`main.k` missing).

- [ ] **Step 3: Write `base`**

`tests/torture/base/main.k` (fixed format, 10-column fields; NODE uses I8/E16, ELEMENT_SHELL uses I8):
```
*KEYWORD
*TITLE
deckcheck torture: base
*CONTROL_TERMINATION
$#  endtim    endcyc     dtmin    endeng    endmas
    1.0E-6
*PART
$#                                                                         title
plate
$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid
         1         1         1
*SECTION_SHELL
$#   secid    elform      shrf       nip     propt   qr/irid     icomp     setyp
         1         2
$#      t1        t2        t3        t4      nloc     marea      idof    edgset
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
$#     mid        ro         e        pr
         1   7.85E-9  210000.0       0.3
*NODE
$#   nid               x               y               z      tc      rc
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
$#   eid     pid      n1      n2      n3      n4
       1       1       1       2       3       4
*END
```
`tests/torture/base/expected.toml`:
```toml
lsdyna_valid = true
findings = []
note = "Clean one-element model; every other case is a variation of this one."
```

- [ ] **Step 4: Write the variations**

Each `main.k` is `base` with the change described. The full text of each is given; do not abbreviate.

`free_format/main.k`: comma-separated cards.
```
*KEYWORD
*TITLE
deckcheck torture: free format
*CONTROL_TERMINATION
1.0E-6
*PART
plate
1,1,1
*SECTION_SHELL
1,2
1.0,1.0,1.0,1.0
*MAT_ELASTIC
1,7.85E-9,210000.0,0.3
*NODE
1,0.0,0.0,0.0
2,10.0,0.0,0.0
3,10.0,10.0,0.0
4,0.0,10.0,0.0
*ELEMENT_SHELL
1,1,1,2,3,4
*END
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "Comma-separated free format on every card."`

`long_format/main.k`: the material in long format (20-column fields) via the keyword's `+` suffix.
```
*KEYWORD
*TITLE
deckcheck torture: long format
*CONTROL_TERMINATION
    1.0E-6
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC +
$#               mid                  ro                   e                  pr
                   1             7.85E-9            210000.0                 0.3
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`,
`note = "One keyword in long format via the + suffix. If LS-DYNA rejects the suffix (Task 3), switch to *KEYWORD LONG=S on line 1 and record which form LS-DYNA accepts."`

`parameter/main.k`: Young's modulus from a `*PARAMETER`.
```
*KEYWORD
*TITLE
deckcheck torture: parameter
*PARAMETER
$#   prmr1      val1
R young     210000.0
*CONTROL_TERMINATION
    1.0E-6
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9    &young       0.3
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "*PARAMETER R young used as &young in MAT_ELASTIC.E."`

`include_path/main.k`: the material lives in `sub/mat.k`, found through `*INCLUDE_PATH`.
```
*KEYWORD
*TITLE
deckcheck torture: include path
*INCLUDE_PATH
sub
*INCLUDE
mat.k
*CONTROL_TERMINATION
    1.0E-6
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
```
`include_path/sub/mat.k`:
```
*KEYWORD
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*END
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "Include resolved through *INCLUDE_PATH, not relative to main.k."`

`comments/main.k`: comment lines inside keyword blocks and between data cards.
```
*KEYWORD
$ a comment before anything
*TITLE
deckcheck torture: comments
*CONTROL_TERMINATION
$ comment between keyword line and card
    1.0E-6
*PART
$ title card next
plate
$ ids card next
         1         1         1
*SECTION_SHELL
         1         2
$ thickness card next
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
$#     mid        ro         e        pr
$ a second comment line
         1   7.85E-9  210000.0       0.3
*NODE
       1             0.0             0.0             0.0
$ comment between node rows
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*END
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "Comment lines in every position LS-DYNA allows; they must not shift card counting."`

`lowercase/main.k`: `base` with every keyword line lowercased and the material as `*mat_elastic_title`.
```
*keyword
*title
deckcheck torture: lowercase
*control_termination
    1.0E-6
*part
plate
         1         1         1
*section_shell
         1         2
       1.0       1.0       1.0       1.0
*mat_elastic_title
steel
         1   7.85E-9  210000.0       0.3
*node
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*element_shell
       1       1       1       2       3       4
*end
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "Lowercase keywords and a _TITLE variant."`

`tabs/main.k`: `base` with the MAT_ELASTIC data card written with tab characters between values instead of
padding. Write it with Python so the tabs are real:
```bash
.venv/Scripts/python.exe -c "from pathlib import Path; s=Path('tests/torture/base/main.k').read_text().replace('         1   7.85E-9  210000.0       0.3','1\t7.85E-9\t210000.0\t0.3').replace('deckcheck torture: base','deckcheck torture: tabs'); Path('tests/torture/tabs/main.k').write_text(s, newline='\n')"
```
`expected.toml`: `lsdyna_valid = true`, `findings = []`,
`note = "Tabs between values. LS-DYNA's own behaviour is the truth: if Task 3 shows it rejects tabs, set lsdyna_valid = false and record that tabs are an error deckcheck should flag (a DC003 candidate)."`

`seeded_mistakes/main.k` (deliberately broken; LS-DYNA would refuse it):
```
*KEYWORD
*INCLUDE
missing_file.k
*PART
$#                                                                         title
bumper
$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid
         1         2        99
*PART
second
         1         2         5
*SECTION_SHELL
$#   secid    elform      shrf       nip     propt   qr/irid     icomp     setyp
         2        16
$#      t1        t2        t3        t4      nloc     marea      idof    edgset
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
$#     mid        ro         e        pr
         5   7.85E-9  210000.0       0.3
*MAT_ELASTIC
         7   7.85E-9  210000.0       0.3
*END
```
`seeded_mistakes/expected.toml` (lines are the true keyword lines):
```toml
lsdyna_valid = false
findings = [
  {rule = "include_missing", line = 2},
  {rule = "references_resolve", line = 4},
  {rule = "duplicate_ids", line = 4},
  {rule = "duplicate_ids", line = 9},
  {rule = "unreferenced_entities", line = 20},
]
note = "Missing include, PART 1 -> MAT 99 undefined, PART 1 defined twice, MAT 7 unused."
```

- [ ] **Step 5: Write the byte-exact cases**

`tests/torture/make_byte_cases.py`:
```python
"""Write the torture cases whose bytes matter: CRLF line endings and a Latin-1 title. Run once; output is committed."""
from pathlib import Path

HERE = Path(__file__).parent
base = (HERE / "base" / "main.k").read_bytes()

crlf = base.replace(b"deckcheck torture: base", b"deckcheck torture: crlf").replace(b"\n", b"\r\n")
(HERE / "crlf").mkdir(exist_ok=True)
(HERE / "crlf" / "main.k").write_bytes(crlf)

latin1 = base.replace(b"deckcheck torture: base", b"deckcheck torture: latin1").replace(b"\nplate\n", b"\nPr\xfcfplatte\n")
(HERE / "latin1").mkdir(exist_ok=True)
(HERE / "latin1" / "main.k").write_bytes(latin1)
```
Run: `.venv/Scripts/python.exe tests/torture/make_byte_cases.py`

`crlf/expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "Windows CRLF line endings throughout."`
`latin1/expected.toml`: `lsdyna_valid = true`, `findings = []`, `note = "Part title contains a Latin-1 byte (0xFC)."`

- [ ] **Step 6: Run the layout test to see it pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_torture_layout.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add tests/torture tests/test_torture_layout.py
git commit -m "Add torture decks with expected outcomes"
```

---

### Task 3: LS-DYNA as the validity oracle

The torture decks claim to be valid LS-DYNA input. LS-DYNA Student decides whether they are.

**Files:**
- Create: `bakeoff/lsdyna_oracle.py`
- Test: `tests/test_lsdyna_oracle.py`

**Interfaces:**
- Consumes: `tests/torture/<case>/` folders and `expected.toml` (Task 2).
- Produces: `lsdyna_reads(case_dir: Path, timeout_s: float = 120) -> tuple[bool, str]`. Returns (normal
  termination, last 40 lines of LS-DYNA's `messag` file or stdout).

- [ ] **Step 1: Write the failing test**

`tests/test_lsdyna_oracle.py`:
```python
import tomllib
from pathlib import Path

import pytest

from bakeoff.lsdyna_oracle import LSDYNA_EXE, lsdyna_reads

TORTURE = Path(__file__).parent / "torture"
needs_lsdyna = pytest.mark.skipif(not LSDYNA_EXE.exists(), reason="LS-DYNA Student not installed")


@pytest.mark.lsdyna
@needs_lsdyna
@pytest.mark.parametrize("case", sorted(p.name for p in TORTURE.iterdir() if (p / "expected.toml").exists()))
def test_torture_deck_matches_lsdyna(case):
    expected = tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))
    ok, log = lsdyna_reads(TORTURE / case)
    assert ok == expected["lsdyna_valid"], f"{case}: LS-DYNA says {ok}\n{log}"
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lsdyna_oracle.py -v`
Expected: FAIL with `ModuleNotFoundError: bakeoff.lsdyna_oracle`.

- [ ] **Step 3: Write the oracle**

`bakeoff/lsdyna_oracle.py`:
```python
"""Run LS-DYNA Student on a deck folder to decide whether it is valid input."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

LSDYNA_EXE = Path(r"C:\Program Files\LS-DYNA Suite R16.1 Student\lsdyna"
                  r"\ls-dyna_smp_d_R16.1_180-gd50332dbe5_winx64_ifort190_sse2_studentversion.exe")
NORMAL = re.compile(r"N\s*o\s*r\s*m\s*a\s*l\s+t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n")


def lsdyna_reads(case_dir: Path, timeout_s: float = 120) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "case"
        shutil.copytree(case_dir, work)
        env = {**os.environ, "LSTC_LICENSE": "Ansys"}
        proc = subprocess.run([str(LSDYNA_EXE), "i=main.k", "ncpu=1"], cwd=work, env=env,
                              capture_output=True, text=True, encoding="latin-1", timeout=timeout_s)
        messag = work / "messag"
        log = messag.read_text(encoding="latin-1") if messag.exists() else proc.stdout
        ok = bool(NORMAL.search(log)) or bool(NORMAL.search(proc.stdout))
        return ok, "\n".join(log.splitlines()[-40:])
```

- [ ] **Step 4: Run the oracle and fix decks until truth is settled**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lsdyna_oracle.py -v -m lsdyna`
Expected: `seeded_mistakes` passes (LS-DYNA refuses it). For each other case that fails:
- If the log shows a syntax error the deck was not meant to have, fix the deck so it expresses its one quirk in
  syntax LS-DYNA accepts. For `long_format`, try `*KEYWORD LONG=S` as the note says.
- If LS-DYNA rejects the quirk itself (likely only `tabs`), set `lsdyna_valid = false` in that case's
  `expected.toml` and add the LS-DYNA message to its `note`.
- Never weaken the test to make it pass.

Re-run until all cases pass. Record every fix in the commit message.

- [ ] **Step 5: Commit**

```bash
git add bakeoff/lsdyna_oracle.py tests/test_lsdyna_oracle.py tests/torture
git commit -m "Check torture decks against LS-DYNA Student"
```

---

### Task 4: Corpus manifest and fetcher

**Files:**
- Create: `bakeoff/corpus.py`
- Create: `tests/corpus/manifest.toml` (empty list for now; Task 7 fills it)
- Test: `tests/test_corpus.py`

**Interfaces:**
- Produces:
  - `Entry` dataclass: `name: str, tier: int, url: str, sha256: str, root: str, terms: str`. `root` is a glob,
    relative to the entry's cache folder, that must match exactly one file: the root deck.
  - `load_manifest(path: Path) -> list[Entry]`
  - `fetch(entry: Entry, cache: Path = CACHE) -> Path`: returns the root deck path. Raises `CorpusHashError` on a
    sha256 mismatch (and deletes the download), and `CorpusRootError` if `root` matches zero or several files.

- [ ] **Step 1: Write the failing tests**

`tests/test_corpus.py`:
```python
import hashlib
import zipfile
from pathlib import Path

import pytest

from bakeoff.corpus import CorpusHashError, CorpusRootError, Entry, fetch, load_manifest


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _zip_with(tmp_path: Path, files: dict[str, bytes]) -> Path:
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return z


def test_fetch_zip_returns_root(tmp_path):
    z = _zip_with(tmp_path, {"model-v1/model/main.key": b"*KEYWORD\n*END\n", "model-v1/model/inc.k": b"*KEYWORD\n"})
    e = Entry("demo", 2, z.as_uri(), _sha(z), "*/model/main.key", "test")
    root = fetch(e, cache=tmp_path / "cache")
    assert root.name == "main.key" and root.read_bytes() == b"*KEYWORD\n*END\n"


def test_fetch_plain_file(tmp_path):
    k = tmp_path / "deck.k"
    k.write_bytes(b"*KEYWORD\n*END\n")
    e = Entry("plain", 1, k.as_uri(), _sha(k), "deck.k", "test")
    assert fetch(e, cache=tmp_path / "cache").read_bytes() == b"*KEYWORD\n*END\n"


def test_fetch_is_cached(tmp_path):
    k = tmp_path / "deck.k"
    k.write_bytes(b"*KEYWORD\n")
    e = Entry("plain", 1, k.as_uri(), _sha(k), "deck.k", "test")
    first = fetch(e, cache=tmp_path / "cache")
    k.unlink()  # source gone: a second fetch must not need it
    assert fetch(e, cache=tmp_path / "cache") == first


def test_hash_mismatch_raises_and_cleans(tmp_path):
    k = tmp_path / "deck.k"
    k.write_bytes(b"*KEYWORD\n")
    e = Entry("bad", 1, k.as_uri(), "0" * 64, "deck.k", "test")
    with pytest.raises(CorpusHashError):
        fetch(e, cache=tmp_path / "cache")
    assert not (tmp_path / "cache" / "bad").exists()


def test_ambiguous_root_raises(tmp_path):
    z = _zip_with(tmp_path, {"a/main.key": b"x", "b/main.key": b"y"})
    e = Entry("amb", 2, z.as_uri(), _sha(z), "*/main.key", "test")
    with pytest.raises(CorpusRootError):
        fetch(e, cache=tmp_path / "cache")


def test_load_manifest(tmp_path):
    m = tmp_path / "manifest.toml"
    m.write_text('[[deck]]\nname = "x"\ntier = 1\nurl = "file:///x"\nsha256 = "ab"\nroot = "x.k"\nterms = "t"\n',
                 encoding="utf-8")
    assert load_manifest(m) == [Entry("x", 1, "file:///x", "ab", "x.k", "t")]
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_corpus.py -v`
Expected: FAIL with `ModuleNotFoundError: bakeoff.corpus`.

- [ ] **Step 3: Write the fetcher**

`bakeoff/corpus.py`:
```python
"""Download external test decks pinned by sha256 into a local cache. They are never committed."""
import hashlib
import shutil
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

CACHE = Path(".corpus")


class CorpusHashError(Exception):
    pass


class CorpusRootError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    tier: int
    url: str
    sha256: str
    root: str
    terms: str


def load_manifest(path: Path) -> list[Entry]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [Entry(**d) for d in data.get("deck", [])]


def _root(entry: Entry, dest: Path) -> Path:
    matches = sorted(dest.glob(entry.root))
    if len(matches) != 1:
        raise CorpusRootError(f"{entry.name}: root {entry.root!r} matched {len(matches)} files")
    return matches[0]


def fetch(entry: Entry, cache: Path = CACHE) -> Path:
    dest = cache / entry.name
    if dest.exists():
        return _root(entry, dest)
    dest.mkdir(parents=True)
    blob = dest / ".download"
    digest = hashlib.sha256()
    with urllib.request.urlopen(entry.url) as r, open(blob, "wb") as f:
        while chunk := r.read(1 << 20):
            digest.update(chunk)
            f.write(chunk)
    if digest.hexdigest() != entry.sha256:
        shutil.rmtree(dest)
        raise CorpusHashError(f"{entry.name}: expected {entry.sha256}, got {digest.hexdigest()}")
    if zipfile.is_zipfile(blob):
        with zipfile.ZipFile(blob) as z:
            z.extractall(dest)
        blob.unlink()
    else:
        blob.rename(dest / Path(entry.root).name)
    return _root(entry, dest)
```

`tests/corpus/manifest.toml`:
```toml
# External decks for M0 and the corpus job. Never commit the decks themselves.
# Each [[deck]]: name, tier (1 breadth, 2 real-world), url, sha256 of the download, root (glob to the root deck),
# terms (what the source's terms allow, and where that was read).
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_corpus.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add bakeoff/corpus.py tests/test_corpus.py tests/corpus/manifest.toml
git commit -m "Add sha256-pinned corpus fetcher"
```

---

### Task 5: Probe — measure dynars on one deck

**Files:**
- Create: `bakeoff/probe.py`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: torture decks (Task 2).
- Produces:
  - `clean_path(p: str) -> str`: strips a leading `\\?\`.
  - `measure(deck_path: str) -> dict` with keys:
    - `deck`, `files`, `parse_s`, `rules_s`
    - `findings`: a list of `{rule, severity, file, line, keyword, message, line_ok}`
    - `round_trip`: `{files, identical}`
    - `edit`: `{tried, status, changed_lines}`
    - on failure, the dict has `error` instead
  - CLI: `python -m bakeoff.probe <deck> <out.json>` writes `measure()`'s result as UTF-8 JSON to `out.json`.

- [ ] **Step 1: Write the failing tests**

`tests/test_probe.py`:
```python
from pathlib import Path

import pytest

from bakeoff.probe import clean_path, measure

TORTURE = Path(__file__).parent / "torture"


def test_clean_path_strips_long_prefix():
    assert clean_path("\\\\?\\C:\\decks\\a.k") == "C:\\decks\\a.k"


def test_clean_path_leaves_plain_paths():
    assert clean_path("C:\\decks\\a.k") == "C:\\decks\\a.k"


def test_seeded_mistakes_findings():
    r = measure(str(TORTURE / "seeded_mistakes" / "main.k"))
    rules = sorted(f["rule"] for f in r["findings"])
    assert rules == ["duplicate_ids", "duplicate_ids", "include_missing", "references_resolve",
                     "unreferenced_entities"]
    assert all(Path(f["file"]).exists() for f in r["findings"] if f["rule"] != "include_missing")


def test_line_ok_is_recorded_per_finding():
    r = measure(str(TORTURE / "seeded_mistakes" / "main.k"))
    missing = next(f for f in r["findings"] if f["rule"] == "include_missing")
    assert missing["line"] == 0 and missing["line_ok"] is False  # known dynars 1.1.0 defect, see spec section 2


@pytest.mark.parametrize("case", ["base", "free_format", "comments", "lowercase", "crlf", "latin1"])
def test_clean_cases_round_trip_and_have_no_errors(case):
    r = measure(str(TORTURE / case / "main.k"))
    assert "error" not in r, r.get("error")
    assert r["round_trip"]["identical"] == r["round_trip"]["files"]
    assert [f for f in r["findings"] if f["severity"] == "Error"] == []


def test_edit_changes_exactly_one_line():
    r = measure(str(TORTURE / "base" / "main.k"))
    assert r["edit"] == {"tried": True, "status": "in_place", "changed_lines": 1}


def test_unparseable_path_reports_error():
    r = measure(str(TORTURE / "does_not_exist.k"))
    assert "error" in r
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_probe.py -v`
Expected: FAIL with `ModuleNotFoundError: bakeoff.probe`.

- [ ] **Step 3: Write the probe**

`bakeoff/probe.py`:
```python
"""Measure dynars on one deck: parse, the four built-in rules, line accuracy, round-trip, one edit."""
import json
import sys
import time
from pathlib import Path

import dynars
from dynars import Rule

RULES = [Rule.references_resolve, Rule.duplicate_ids, Rule.include_missing, Rule.unreferenced_entities]


def clean_path(p: str) -> str:
    return p[4:] if p.startswith("\\\\?\\") else p


def _line_at(path: str, n: int) -> str:
    if n < 1 or not Path(path).exists():
        return ""
    with open(path, "rb") as f:
        for i, raw in enumerate(f, 1):
            if i == n:
                return raw.decode("latin-1").rstrip("\r\n")
    return ""


def _line_ok(file: str, line: int, keyword: str) -> bool:
    return _line_at(file, line).upper().startswith("*" + keyword.upper())


def _round_trip(deck) -> dict:
    same = [Path(clean_path(f.path)).read_bytes() == f.to_bytes() for f in deck.files()]
    return {"files": len(same), "identical": sum(same)}


def _one_edit(deck) -> dict:
    parts = deck.keywords("PART")
    if not parts:
        return {"tried": False}
    kw = parts[0]
    owner = next(f for f in deck.files() if clean_path(f.path) == clean_path(kw.file))
    before = owner.to_bytes().splitlines()
    status = kw.set_field("grav", (kw.field("grav") or 0) + 1)
    after = owner.to_bytes().splitlines()
    changed = sum(a != b for a, b in zip(before, after)) + abs(len(before) - len(after))
    return {"tried": True, "status": status, "changed_lines": changed}


def measure(deck_path: str) -> dict:
    try:
        t0 = time.perf_counter()
        deck = dynars.parse_deck(deck_path)
        t1 = time.perf_counter()
        report = deck.validate([make() for make in RULES])
        t2 = time.perf_counter()
        findings = []
        for f in report.findings:
            file = clean_path(f.file)
            findings.append({"rule": f.rule, "severity": repr(f.severity).split(".")[-1], "file": file,
                             "line": f.line, "keyword": f.keyword, "message": f.message,
                             "line_ok": _line_ok(file, f.line, f.keyword)})
        return {"deck": deck_path, "files": len(deck.files()), "parse_s": round(t1 - t0, 3),
                "rules_s": round(t2 - t1, 3), "findings": findings, "round_trip": _round_trip(deck),
                "edit": _one_edit(deck)}
    except Exception as e:  # measurement must record failures, not crash the run
        return {"deck": deck_path, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    result = measure(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_probe.py -v`
Expected: all pass. If a torture case fails, that is an M0 finding, not a test to loosen:
- Check that `severity` renders as `Error` / `Warning` (adjust the `repr` parsing only if dynars prints severity
  differently).
- For any other failure, mark that parametrized case `xfail` with the observed behaviour as the reason. Add the
  observation to `bakeoff/findings.md`, creating the file with a `# M0 observations` heading if needed.

- [ ] **Step 5: Commit**

```bash
git add bakeoff/probe.py tests/test_probe.py bakeoff/findings.md
git commit -m "Add dynars probe: rules, line accuracy, round-trip, one edit"
```

---

### Task 6: Runner with memory watchdog

**Files:**
- Create: `bakeoff/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `bakeoff.probe` CLI (Task 5), `load_manifest` / `fetch` (Task 4).
- Produces:
  - `run_one(deck: Path, cap_mb: int = 4096, timeout_s: float = 1800) -> dict`: the probe's result plus
    `peak_mb`, or an `error` row on cap, timeout or crash.
  - CLI: `python -m bakeoff.run [--torture] [--corpus] [--out bakeoff/results/<name>.jsonl]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_run.py`:
```python
from pathlib import Path

from bakeoff.run import run_one

TORTURE = Path(__file__).parent / "torture"


def test_run_one_returns_probe_result_with_peak():
    r = run_one(TORTURE / "seeded_mistakes" / "main.k")
    assert len(r["findings"]) == 5 and r["peak_mb"] > 0


def test_run_one_kills_at_cap():
    r = run_one(TORTURE / "base" / "main.k", cap_mb=1)
    assert r["error"].startswith("exceeded memory cap")


def test_run_one_large_output(tmp_path):
    deck = tmp_path / "many.k"
    lines = ["*KEYWORD"]
    for i in range(1, 3001):  # 3000 unused materials -> 3000 warnings, a large JSON result
        lines += ["*MAT_ELASTIC", f"{i:>10d}   7.85E-9  210000.0       0.3"]
    deck.write_text("\n".join(lines + ["*END", ""]), encoding="ascii")
    r = run_one(deck, timeout_s=300)
    assert "error" not in r and len(r["findings"]) == 3000
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: bakeoff.run`.

- [ ] **Step 3: Write the runner**

`bakeoff/run.py`:
```python
"""Run the probe on decks in child processes, under a memory cap, and write one JSON line per deck."""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from bakeoff.corpus import fetch, load_manifest

TORTURE = Path("tests/torture")
MANIFEST = Path("tests/corpus/manifest.toml")


def run_one(deck: Path, cap_mb: int = 4096, timeout_s: float = 1800) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        proc = subprocess.Popen([sys.executable, "-m", "bakeoff.probe", str(deck), str(out)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        watched, peak, start = psutil.Process(proc.pid), 0, time.monotonic()
        while proc.poll() is None:
            try:
                peak = max(peak, watched.memory_info().rss)
            except psutil.NoSuchProcess:
                break
            if peak > cap_mb * 2**20 or time.monotonic() - start > timeout_s:
                proc.kill()
                proc.wait()
                why = f"exceeded memory cap {cap_mb} MB" if peak > cap_mb * 2**20 else f"timeout {timeout_s} s"
                return {"deck": str(deck), "error": why, "peak_mb": round(peak / 2**20, 1)}
            time.sleep(0.05)
        stderr = proc.stderr.read().decode("utf-8", "replace")
        if not out.exists():
            return {"deck": str(deck), "error": f"probe crashed: {stderr[-2000:]}", "peak_mb": round(peak / 2**20, 1)}
        result = json.loads(out.read_text(encoding="utf-8"))
        result["peak_mb"] = round(peak / 2**20, 1)
        return result


def _decks(torture: bool, corpus: bool) -> list[Path]:
    decks = sorted(TORTURE.glob("*/main.k")) if torture else []
    if corpus:
        decks += [fetch(e) for e in load_manifest(MANIFEST)]
    return decks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for deck in _decks(args.torture, args.corpus):
            row = run_one(deck)
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(deck, "error" if "error" in row else f"{len(row['findings'])} findings", row.get("peak_mb"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_run.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the torture tier end to end**

Run: `.venv/Scripts/python.exe -m bakeoff.run --torture --out bakeoff/results/torture.jsonl`
Expected: one line per case printed, no `error` except where Task 5 recorded one.

- [ ] **Step 6: Commit**

```bash
git add bakeoff/run.py tests/test_run.py bakeoff/results/torture.jsonl
git commit -m "Add watchdog runner; record torture-tier results"
```

---

### Task 7: Fill the corpus manifest

This task is research plus records. Every entry is verified by downloading it once.

**Files:**
- Modify: `tests/corpus/manifest.toml`
- Create: `docs/corpus-terms.md`

**Interfaces:**
- Produces: manifest entries consumed by `bakeoff.run --corpus` (Task 6).

- [ ] **Step 1: VIVA+ (tier 2)**

URL (GitLab archive of tag v2.0.2):
`https://openvt.eu/api/v4/projects/171/repository/archive.zip?sha=v2.0.2`

Root deck inside the archive: `model/50M-seated/vivaplus-50M.key`.

Download it once and hash it:
```bash
curl -L -o /tmp/viva.zip "https://openvt.eu/api/v4/projects/171/repository/archive.zip?sha=v2.0.2" && sha256sum /tmp/viva.zip && unzip -l /tmp/viva.zip | grep "vivaplus-50M.key"
```
Add the entry, with the archive's top folder replaced by `*`:
```toml
[[deck]]
name = "vivaplus-50M-seated-v2.0.2"
tier = 2
url = "https://openvt.eu/api/v4/projects/171/repository/archive.zip?sha=v2.0.2"
sha256 = "<the value sha256sum printed>"
root = "*/model/50M-seated/vivaplus-50M.key"
terms = "LGPL v3 (model/LICENSE/lgpl-3.0.txt in the archive; vivaplus.readthedocs.io). Download at test time; never commit."
```
If the GitLab archive's bytes differ between downloads (archives can be regenerated), the hash check will fail
on the next fetch. In that case, pin the commit sha (`cc986b7df66b...`, full sha from the tags API) instead of
the tag and re-hash.

- [ ] **Step 2: LS-DYNA example decks (tier 1)**

Open https://www.dynaexamples.com (it returned HTTP 503 on 2026-10-28; retry). Do two things:
- Read its terms of use and record them in `docs/corpus-terms.md` with the date read.
- Choose 20 to 30 examples spread across keyword families: at least 3 each of contact, materials, implicit,
  ALE/SPH, and airbag/seatbelt or restraint, if offered.

For each example, add one `[[deck]]` with `tier = 1`, the direct download URL, its sha256 and the root deck
name. If the terms forbid automated download, stop and ask Chintan before adding any.

- [ ] **Step 3: One CCSA/NCAC vehicle model (tier 2)**

Open https://www.ccsa.gmu.edu/models/ and read the terms. Pick the smallest full-vehicle LS-DYNA model offered
(for example a Toyota Yaris), record its terms, and add its entry. If registration or a click-through is
required, stop and ask Chintan to download it himself. In that case, add the entry with
`url = "file:///<his local path>"` and a `terms` line saying it is local-only.

- [ ] **Step 4: Fetch everything once**

Run: `.venv/Scripts/python.exe -c "from bakeoff.corpus import fetch, load_manifest; from pathlib import Path; [print(fetch(e)) for e in load_manifest(Path('tests/corpus/manifest.toml'))]"`
Expected: one root path printed per entry, no `CorpusHashError`.

- [ ] **Step 5: Commit**

```bash
git add tests/corpus/manifest.toml docs/corpus-terms.md
git commit -m "Pin M0 corpus: VIVA+, LS-DYNA examples, CCSA vehicle"
```

---

### Task 8: Corpus run and triage

**Files:**
- Create: `bakeoff/results/corpus.jsonl` (committed: findings only, no deck content)
- Create: `bakeoff/triage.md`

- [ ] **Step 1: Tell Chintan before the long run**

The vehicle and VIVA+ decks may take minutes each and up to 4 GB. State the expected duration from the torture
timings and wait for his go-ahead.

- [ ] **Step 2: Run**

Run: `.venv/Scripts/python.exe -m bakeoff.run --corpus --out bakeoff/results/corpus.jsonl`
Expected: one line per deck, each either findings or a recorded error.

- [ ] **Step 3: Triage every finding**

For each finding in `corpus.jsonl`, open the reported file and line and classify it:
- **real defect** in the deck (for example, a material that really is unused);
- **dynars false alarm**;
- **line wrong** (the finding is right but `line_ok` is false or the line is off).

Write `bakeoff/triage.md`: one table per deck with columns rule · file:line · class · one-line reason. Where a
rule has more than 30 findings on one deck, triage a random sample of 30 (seed 0) and say so. That cap mainly
bites `unreferenced_entities` on VIVA+.

- [ ] **Step 4: Commit**

```bash
git add bakeoff/results/corpus.jsonl bakeoff/triage.md
git commit -m "M0 corpus run and triage"
```

---

### Task 9: Assessment and go/no-go

**Files:**
- Create: `docs/m0-assessment.md`
- Modify: `docs/specs/2026-10-27-deckcheck-design.md` (section 7: record the result)

- [ ] **Step 1: Write the assessment**

`docs/m0-assessment.md` reports each of the spec's five pass criteria (section 7) as measured. For each, give
the number and the evidence file:
1. Parse: decks parsed / total; peak MB and seconds for the largest deck.
2. Rule accuracy: findings per rule, false alarms per rule (from `triage.md`).
3. Line accuracy: the share of findings whose `line_ok` is true per rule, and the pattern of the misses (it feeds
   M1's position layer).
4. Round-trip and edit: files identical / total, and edit status on each deck.
5. Formats: which torture cases dynars handled, and which LS-DYNA itself rejected.

End with **GO** or **NO-GO** and one paragraph of reasons. NO-GO when dynars crashes on, or false-alarms on, VIVA+
or the vehicle model in a way that a thin layer cannot fix.

- [ ] **Step 2: Record it in the spec**

Append to spec section 7: `M0 result (YYYY-MM-DD): GO|NO-GO — see docs/m0-assessment.md.`

- [ ] **Step 3: Commit**

```bash
git add docs/m0-assessment.md docs/specs/2026-10-27-deckcheck-design.md
git commit -m "M0 assessment: dynars go/no-go"
```

- [ ] **Step 4: Gate**

Stop. Present the assessment to Chintan. Update the project report doc's status and decision log. Do not start
M1 planning until he has read it and chosen to continue.
