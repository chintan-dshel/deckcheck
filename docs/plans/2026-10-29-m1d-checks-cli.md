# M1d: Checks, command line, packaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn M1c's index into a tool an engineer runs: `deckcheck model.k` prints DC001–DC006 findings at exact
lines and columns, then a "Not checked" footer, in text or JSON, with CI exit codes, installable from a wheel with
no runtime dependencies. Zero unexplained findings on the corpus.

**Architecture:**
- **LS-DYNA decides first** (Task 1). Torture cases decide:
  - which set references LS-DYNA accepts unchecked (DC006 vs DC001);
  - which duplicate kinds it accepts (DC002 severity);
  - whether overflow and mixed format are silent misreads (DC003 scope);
  - how `*MAT_USER_DEFINED_MATERIAL_MODELS` is read.
- **Diagnostics are records; rules are functions.** `deckcheck.diagnostics` holds `Diagnostic`, `Related`,
  `NotChecked` and `Report`. Each rule in `deckcheck.rules.*` is `(tree, ix) -> list[Diagnostic]`.
  `deckcheck.rules.check(main)` runs them all. `deckcheck.coverage.not_checked(tree, ix)` lists what was not checked.
- **The index gains three things** (Task 2):
  - unchecked references with their locations (`Index.ignored()`, for DC006);
  - per-block failures caught and recorded (`Index.failures`, for DC000), so one reader bug never stops a run;
  - file names in its uncertainty reasons, for the footer.
- **Front door.** `deckcheck.cli` formats a `Report` as text or JSON and sets the exit code. It contains no checking
  logic.
- **Evidence.** Torture expectations, a DC005 audit test over the keyword data, and a corpus gate run through the
  real checks under the 2 GB cap.

**Tech Stack:** Python 3.12, stdlib only at runtime (`argparse`, `json`, `tomllib`, `importlib`). pytest. LS-DYNA
R16.1 Student as referee (`bakeoff/lsdyna_oracle.py`). psutil for the capped corpus run. hatchling to build the
wheel.

**Spec:** `docs/specs/2026-10-27-deckcheck-design.md`, as revised for M1d (commit ce8a5e2). These sections bind this
plan:
- §4 (rules, diagnostics, front doors; error handling);
- §5 (the three finding classes, the six checks, coverage is never a diagnostic);
- §6 (CLI, text, JSON, exit codes);
- §8 (verification by class);
- §9 (layout, no runtime dependencies);
- §11 (M1 done);
- §12 (edge-case register).

Read `docs/m1c-field-reader-index.md` §6 too: it lists what M1d consumes from the index.

## Global Constraints

- Runtime dependencies: none beyond the standard library (§9).
- The name and branding never use "LS-DYNA", only "for LS-DYNA" descriptively. Never copy the keyword manual (§2).
- External decks are never committed. Results files hold names, counts, ids and line numbers only.
- Downloaded decks are untrusted data: parse only, never execute.
- Every corpus run under a 2 GB memory cap (the laptop has 7.7 GB).
- Which class a pattern falls in (§5) is decided by LS-DYNA on a torture case, never assumed.
- Never push, create a GitHub remote, or publish to PyPI without Chintan's explicit yes.
- Work on branch `m1d`, never `main`. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Use the Edit tool for code edits, not bash heredocs (they mangle `\n` escapes on this machine).
- Test command: `.venv/Scripts/python -m pytest` (the system Python lacks the editable install).

## Review Focus

1. **A deck on another drive than the working folder** (`D:\decks\a.k` run from `C:\`): `os.path.relpath` raises
   `ValueError` on Windows. Expected: the absolute path is printed, no crash. Pinned in Task 6
   (`test_path_on_another_drive_prints_absolute`).
2. **Output the console can't encode** (a folder named `モデル` on a cp1252 console). Expected: the output prints,
   with unencodable characters replaced, and no traceback. Pinned in Task 6 (`test_unencodable_path_does_not_crash`).
3. **A main path that is missing or is a folder.** Expected: one line on stderr, exit code 2, no traceback. Pinned
   in Task 6 (`test_missing_or_folder_main_exits_2`).
4. **A reader bug inside one block.** Expected: a DC000 diagnostic for that block, its kinds marked not checked, and
   every other block still checked. Pinned in Task 2 (`test_block_failure_is_recorded_and_run_continues`) and Task 3
   (`test_dc000_reports_block_failure`).
5. **`--ignore` with lowercase or unknown codes.** Expected: `dc005` works like `DC005`; an unknown code is a bad
   argument (exit 2, names the known codes). Pinned in Task 6 (`test_ignore_codes`).

---

### Task 1: LS-DYNA decides the M1d cases

**Files:**
- Create: `tests/torture/make_m1d_cases.py`, `tests/torture/m1d_*/` (15 cases), `bakeoff/m1d_winner.py`,
  `bakeoff/results/m1d_referee.txt`
- Modify: `tests/test_torture_layout.py` (CASES), `src/deckcheck/data/overrides.toml` (DC006 keywords),
  `docs/specs/2026-10-27-deckcheck-design.md` (§12 register rows)

**Interfaces:**
- Produces, for Task 3:
  - the referee verdict per case in each `expected.toml` (`lsdyna_valid`);
  - `when = "unchecked"` overrides for every set reference LS-DYNA accepted with the set missing;
  - the dict `ACCEPTED_DUPLICATES: dict[str, str]` (kind → `"first"`, `"last"` or `"unknown"`), written into
    `bakeoff/results/m1d_referee.txt` and copied into `deckcheck.rules.duplicates` in Task 3.
- Produces, for Task 4: the overflow and mixed-format verdicts.

- [ ] **Step 1: Write the case generator**

The probed set fields are already linked in the data (checked during planning): `BOUNDARY_PRESCRIBED_MOTION_SET.nsid`,
`LOAD_NODE_SET.nsid`, `INITIAL_VELOCITY.nsid` and `DATABASE_HISTORY_NODE_SET.id1` link to SET_NODE;
`LOAD_SEGMENT_SET.ssid` links to SET_SEGMENT. The base model is the `spc_set_none` model with a curve and a node set
added. Its lines 1–27 are fixed, so the probe always sits at line 28 (keyword) and line 29 (first card).

```python
"""M1d torture cases (docs/plans/2026-10-29-m1d-checks-cli.md, Task 1). Writes main.k always; writes expected.toml
once VERDICT holds LS-DYNA's answer for the case. Run: .venv/Scripts/python tests/torture/make_m1d_cases.py"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def i10(*vals):
    return "".join(f"{v:>10}" for v in vals)


def i20(*vals):
    return "".join(f"{v:>20}" for v in vals)


BASE = "\n".join([
    "*KEYWORD", "*TITLE", "deckcheck torture: {title}", "*CONTROL_TERMINATION", "    1.0E-6",
    "*PART", "plate", i10(1, 1, 1),
    "*SECTION_SHELL", i10(1, 2), i10(1.0, 1.0, 1.0, 1.0),
    "*MAT_ELASTIC", i10(1, "7.85E-9", "210000.0", 0.3),
    "*NODE", "       1             0.0             0.0             0.0", "       2            10.0             0.0             0.0",
    "       3            10.0            10.0             0.0", "       4             0.0            10.0             0.0",
    "*ELEMENT_SHELL", "       1       1       1       2       3       4",
    "*DEFINE_CURVE", i10(1), i20(0.0, 1.0), i20(1.0, 1.0),
    "*SET_NODE_LIST", i10(1), i10(1, 2),
]) + "\n{extra}*END\n"

SEGMENT = "*SET_SEGMENT\n" + i10(2) + "\n" + i10(1, 2, 3, 4) + "\n"

# name -> (title, extra text from line 28, the probed (kind, id, line, columns) or None)
CASES = {
    "m1d_base": ("base model for M1d cases", "", None),
    "m1d_bpm_set_none": ("prescribed motion names a missing node set",
                         "*BOUNDARY_PRESCRIBED_MOTION_SET\n" + i10(99, 3, 0, 1, 1.0) + "\n", ("SET_NODE", 99, 29, [8, 10])),
    "m1d_load_node_set_none": ("nodal load names a missing node set",
                               "*LOAD_NODE_SET\n" + i10(99, 3, 1, 1.0) + "\n", ("SET_NODE", 99, 29, [8, 10])),
    "m1d_load_segment_set_none": ("pressure load names a missing segment set",
                                  "*LOAD_SEGMENT_SET\n" + i10(99, 1, 1.0) + "\n", ("SET_SEGMENT", 99, 29, [8, 10])),
    "m1d_initial_velocity_none": ("initial velocity names a missing node set",
                                  "*INITIAL_VELOCITY\n" + i10(99) + "\n" + i10(0.0, 0.0, 1.0) + "\n",
                                  ("SET_NODE", 99, 29, [8, 10])),
    "m1d_history_node_set_none": ("history output names a missing node set",
                                  "*DATABASE_HISTORY_NODE_SET\n" + i10(99) + "\n", ("SET_NODE", 99, 29, [8, 10])),
    "m1d_dup_part": ("part 1 defined twice", "*PART\nplate again\n" + i10(1, 1, 1) + "\n", ("PART", 1, 30, [9, 10])),
    "m1d_dup_mat": ("material 1 defined twice, second with E = 70000",
                    "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "70000.0", 0.3) + "\n", ("MAT", 1, 29, [9, 10])),
    "m1d_dup_section": ("section 1 defined twice, second 2.0 thick",
                        "*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(2.0, 2.0, 2.0, 2.0) + "\n", ("SECTION", 1, 29, [9, 10])),
    "m1d_dup_curve": ("curve 1 defined twice",
                      "*DEFINE_CURVE\n" + i10(1) + "\n" + i20(0.0, 2.0) + "\n" + i20(1.0, 2.0) + "\n",
                      ("DEFINE_CURVE", 1, 29, [9, 10])),
    "m1d_dup_node_set": ("node set 1 defined twice", "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(3, 4) + "\n",
                         ("SET_NODE", 1, 29, [9, 10])),
    "m1d_dup_node": ("node 1 defined twice",
                     "*NODE\n       1             0.0             0.0             5.0\n", ("NODE", 1, 29, [7, 8])),
    "m1d_overflow_node": ("a 9-digit node id spills into the 8-wide id field's neighbour",
                          "*NODE\n123456789             5.0             5.0             0.0\n", None),
    "m1d_mixed_free": ("two values in one comma-separated slot",
                       "*MAT_ELASTIC\n" + "         2,7.85E-9,  210000.0       0.3" + "\n", None),
    "m1d_umat": ("user-defined material (umat41) on a second part",
                 "*PART\nuser material\n" + i10(2, 1, 2) + "\n*MAT_USER_DEFINED_MATERIAL_MODELS\n"
                 + i10(2, "7.85E-9", 41, 4, 0, 0, 3, 4) + "\n" + i10(0, 0, 0, 0, 0, 0) + "\n"
                 + i10("210000.0", 0.3, "175000.0", "80769.2") + "\n", None),
}

# Filled in Step 3 from bakeoff/results/m1d_referee.txt: name -> (lsdyna_valid, note quoting the deciding line)
VERDICT: dict[str, tuple[bool, str]] = {}


def expected(name: str, probe, valid: bool, note: str) -> str:
    lines = [f"lsdyna_valid = {'true' if valid else 'false'}", "findings = []", f"note = {json.dumps(note)}"]
    if probe and name.startswith("m1d_dup_"):
        kind, id_, line, cols = probe
        lines += ["", "[index]", f'duplicates = [{{kind = "{kind}", id = {id_}, file = "main.k", line = {line}, '
                  f"columns = [{cols[0]}, {cols[1]}]}}]"]
    elif probe and not valid:  # rejected: the missing set is a dangling reference (DC001)
        kind, id_, line, cols = probe
        lines += ["", "[index]", f'dangling = [{{kind = "{kind}", id = {id_}, file = "main.k", line = {line}, '
                  f"columns = [{cols[0]}, {cols[1]}]}}]"]
    elif probe:  # accepted with the set missing: LS-DYNA doesn't check it (DC006, Task 3)
        kind, id_, line, cols = probe
        lines += ["", "[[diagnostics]]", 'code = "DC006"', 'severity = "warning"', 'file = "main.k"',
                  f"line = {line}", f"columns = [{cols[0]}, {cols[1]}]"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for name, (title, extra, probe) in CASES.items():
        folder = HERE / name
        folder.mkdir(exist_ok=True)
        (folder / "main.k").write_bytes(BASE.format(title=title, extra=extra).encode("latin-1"))
        if name in VERDICT:
            (folder / "expected.toml").write_text(expected(name, probe, *VERDICT[name]), encoding="utf-8")
```

- [ ] **Step 2: Generate the decks and ask LS-DYNA**

Run:
```
.venv/Scripts/python tests/torture/make_m1d_cases.py
.venv/Scripts/python -m bakeoff.referee_cases m1d_base m1d_bpm_set_none m1d_load_node_set_none m1d_load_segment_set_none m1d_initial_velocity_none m1d_history_node_set_none m1d_dup_part m1d_dup_mat m1d_dup_section m1d_dup_curve m1d_dup_node_set m1d_dup_node m1d_overflow_node m1d_mixed_free m1d_umat > bakeoff/results/m1d_referee.txt
```
Expected: `m1d_base` is accepted. If it isn't, fix the base before reading any other verdict: every other case
inherits it.

Read the log tail of each rejection. A rejection counts for the probe only if its deciding line names the probe
(the id 99, or the duplicated id). Otherwise the case is broken: fix it and rerun.

- [ ] **Step 3: Find which definition wins for each accepted duplicate**

Create `bakeoff/m1d_winner.py`:

```python
"""For an accepted duplicate case, run LS-DYNA and print d3hsp lines that echo either definition's distinguishing
value, so the winner can be read off: python -m bakeoff.m1d_winner <case> <first value> <second value>."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bakeoff.lsdyna_oracle import LSDYNA_EXE

case, values = Path("tests/torture") / sys.argv[1], sys.argv[2:]
with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "case"
    shutil.copytree(case, work)
    subprocess.run([str(LSDYNA_EXE), "i=main.k", "ncpu=1"], cwd=work, env={**os.environ, "LSTC_LICENSE": "Ansys"},
                   capture_output=True, timeout=120)
    text = (work / "d3hsp").read_text(encoding="latin-1") if (work / "d3hsp").exists() else ""
    for n, line in enumerate(text.splitlines(), 1):
        if any(v in line for v in values):
            print(n, line.rstrip())
```

For each accepted `m1d_dup_*` case, run it with the two definitions' distinguishing values as LS-DYNA echoes them.
For example `python -m bakeoff.m1d_winner m1d_dup_mat 2.100E+05 7.000E+04`. First check the echo format in the
d3hsp of `m1d_base` and adjust the value strings to match. Interpret the result:
- Only the first value is echoed: winner `"first"`.
- Only the second: `"last"`.
- Neither, or both: `"unknown"`.

Append to `bakeoff/results/m1d_referee.txt`:

```
== ACCEPTED_DUPLICATES (Task 1 Step 3)
{"<KIND>": "<first|last|unknown>", ...}
```

- [ ] **Step 4: Write the expectations and the DC006 overrides**

Fill `VERDICT` in `make_m1d_cases.py` from the referee file, one entry per case. Use `(True, "...")` or
`(False, "...")`, with a note quoting LS-DYNA's deciding line (rejections) or "accepted, no warning" (acceptances).
Rerun the generator.

For `m1d_overflow_node`, `m1d_mixed_free` and `m1d_umat`, the generator writes no `[index]` or `[[diagnostics]]`.
Their deckcheck expectations are added in Tasks 4 and 5.

For every `*_set_none` case LS-DYNA accepted, append to `src/deckcheck/data/overrides.toml`:

```toml
[[override]]
keyword = "<KEYWORD>"
field = "<field>"
set = { when = "unchecked" }
evidence = "tests/torture/<case> (names set 99, none defined: LS-DYNA R16.1 Student accepted, no warning)"
reason = "LS-DYNA accepts a missing set here: the id counts as a use, and DC006 reports it as having no effect."
```

`set = { when = "unchecked" }` keeps the existing link: confirm by comparing with the `BOUNDARY_SPC_SET` override
at `overrides.toml:143-147`.

- [ ] **Step 5: Register the cases and run the index tests**

Add all 15 case names to `CASES` in `tests/test_torture_layout.py`.

Run: `.venv/Scripts/python -m pytest tests/test_torture_layout.py tests/test_index.py -q`
Expected: PASS. `test_torture_index` reads the new `[index]` tables: a rejected missing set is dangling, a
duplicate is listed, and an accepted missing set is neither.

If a duplicate case fails because the index doesn't list the duplicate, check the kind's definer row in
`data/definers.toml` before changing code.

- [ ] **Step 6: Update the edge-case register**

In spec §12, change the "untested; M1d tests" rows for the set keywords, duplicates and overflow/mixed format to
"tested", naming each case and its verdict. Leave the user-defined-material row for Task 5.

- [ ] **Step 7: Commit**

```bash
git add tests/torture/make_m1d_cases.py tests/torture/m1d_* tests/test_torture_layout.py bakeoff/m1d_winner.py bakeoff/results/m1d_referee.txt src/deckcheck/data/overrides.toml docs/specs/2026-10-27-deckcheck-design.md
git commit -m "M1d Task 1: LS-DYNA decides missing sets, duplicates, overflow, mixed format, umat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Diagnostics records, index additions, coverage

**Files:**
- Create: `src/deckcheck/diagnostics.py`, `src/deckcheck/coverage.py`, `tests/test_coverage.py`
- Modify: `src/deckcheck/index.py` (`Index.unchecked`, `Index.ignored()`, `Index.failures`, try/except in `build`,
  file names in reasons)
- Test: `tests/test_index.py` (append)

**Interfaces:**
- Produces:
  - `Diagnostic(path: Path, line: int, start: int, end: int, severity: str, code: str, message: str, related: tuple[Related, ...] = ())`.
    Columns are 0-based with `end` exclusive, as the index stores them; the CLI adds 1.
  - `Related(path: Path, line: int, message: str)`.
  - `NotChecked(what: str, reasons: tuple[str, ...], count: int)`.
  - `Report(main: Path, diagnostics: list[Diagnostic], not_checked: list[NotChecked])`.
  - `Index.ignored() -> list[Ref]`: unchecked references whose target isn't defined, on checked kinds.
  - `Index.failures: list[tuple[int, int, str]]`: (file index, block line, "*NAME: Error: text").
  - `deckcheck.coverage.DC005_KINDS = ("MAT", "SECTION", "HOURGLASS")`.
  - `deckcheck.coverage.dc005_silent(tree, ix) -> dict[str, str]`: kind → the reason DC005 stays silent.
  - `deckcheck.coverage.not_checked(tree, ix) -> list[NotChecked]`.

- [ ] **Step 1: Write the failing index tests**

Append to `tests/test_index.py`:

```python
def test_unchecked_reference_to_missing_set_is_ignored_not_dangling():
    ix = build(resolve_tree(TORTURE / "spc_set_none" / "main.k"))
    assert ix.dangling() == []
    [r] = ix.ignored()
    assert (r.kind, r.id, r.path.name, r.line, r.start, r.end, r.field) == (
        "SET_NODE", 99, "main.k", 22, 8, 10, "BOUNDARY_SPC_SET.nsid")


def test_unchecked_reference_to_defined_set_is_not_ignored():
    ix = build(resolve_tree(TORTURE / "spc_set_id" / "main.k"))
    assert ix.ignored() == []


def test_block_failure_is_recorded_and_run_continues(tmp_path, monkeypatch):
    import deckcheck.index as index_mod
    real = index_mod.read_fields

    def flaky(block, *args, **kwargs):
        if block.name == "MAT_ELASTIC":
            raise RuntimeError("boom")
        return real(block, *args, **kwargs)

    monkeypatch.setattr(index_mod, "read_fields", flaky)
    ix = index(tmp_path, BASE + "*PART\nother\n" + i10(2, 1, 99) + "\n")
    [(fi, line, text)] = ix.failures
    assert (fi, text) == (0, "*MAT_ELASTIC: RuntimeError: boom")
    assert "MAT" in ix.uncertain_defs           # its definitions can't be seen: DC001 stays silent on MAT
    assert 1 in ix.defs.get("SECTION", {})     # the rest of the deck was still read


def test_uncertain_reasons_name_the_file(tmp_path):
    ix = index(tmp_path, BASE + "*PART\nother\n" + i10(2, 1, "&nope") + "\n")
    assert any(r.startswith("main.k:") for r in ix.uncertain_uses["MAT"])
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_index.py -q -k "ignored or failure or reasons_name"`
Expected: FAIL with `AttributeError: 'Index' object has no attribute 'ignored'`, then `failures`. The reasons test
fails because the reason reads `"10: reference not known"` with no file name. The spc line numbers come from
`tests/torture/spc_set_none/main.k`: the `*BOUNDARY_SPC_SET` card is line 22. Check this before trusting the
assertion.

- [ ] **Step 3: Implement the index additions**

In `src/deckcheck/index.py`:

1. Add fields to `Index`, after `problems`:
```python
    unchecked: list[tuple[str, int, int, str]] = field(default_factory=list)  # kind, id, packed loc, "KEY.field"
    failures: list[tuple[int, int, str]] = field(default_factory=list)        # file index, block line, what failed
```
2. Add after `dangling`:
```python
    def ignored(self) -> list[Ref]:
        """References LS-DYNA accepts without checking (link_when "unchecked") whose target is not defined (DC006)."""
        out = []
        for kind, id_, loc, name in self.unchecked:
            if self.checked(kind) and not any(id_ in self.defs.get(k, {}) for k in LOOKUP.get(kind, (kind,))):
                out.append(Ref(kind, id_, *self.where(loc), name))
        return sorted(out, key=lambda r: (str(r.path), r.line, r.start))
```
3. In `_reference`, the `link_when == "unchecked"` branch records the location too:
```python
        if spec.get("link_when") == "unchecked":  # LS-DYNA accepts a missing target here: a use, never dangling
            self.possible.setdefault(kind, set()).add(abs(v) + shift)
            self.unchecked.append((kind, abs(v) + shift, pack(fi, f.line, f.start, f.end), f"{key}.{f.name}"))
            return
```
4. Uncertainty reasons name the file. Add a helper to `Index`:
```python
    def _at(self, fi: int, line: int) -> str:
        return f"{self.tree.files[fi].path.name}:{line}"
```
   Then in `_define` and `_reference`, replace each `f"{f.line}: ..."` reason with `f"{self._at(fi, f.line)}: ..."`.
   That is "id not known", "id not an integer", "id out of range", "not mapped", "reference not known" and
   "reference not an id".
5. In `build`, wrap the read of one block so a failure is recorded and the run continues:
```python
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
```
   (`read_fields` may be a generator. Keep the whole loop inside `try`, so an exception raised mid-iteration is
   caught too.)

- [ ] **Step 4: Run the index tests**

Run: `.venv/Scripts/python -m pytest tests/test_index.py -q`
Expected: PASS, including every existing index test.

- [ ] **Step 5: Write the diagnostics records**

`src/deckcheck/diagnostics.py`:

```python
"""What a check reports (spec §4, diagnostics row). Columns are 0-based, end exclusive, as the index stores them;
front doors convert. Coverage (what was not checked) is kept apart from diagnostics: it is never a finding (§5)."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Related:
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    line: int
    start: int
    end: int
    severity: str  # "error" | "warning"
    code: str
    message: str
    related: tuple[Related, ...] = ()


@dataclass(frozen=True)
class NotChecked:
    what: str                 # e.g. "references to MAT (DC001, DC006)"
    reasons: tuple[str, ...]  # the first few, each "file:line why"
    count: int                # how many places in all


@dataclass
class Report:
    main: Path
    diagnostics: list[Diagnostic]
    not_checked: list[NotChecked]
```

- [ ] **Step 6: Write the failing coverage tests**

`tests/test_coverage.py`:

```python
from pathlib import Path

from deckcheck.coverage import DC005_KINDS, dc005_silent, not_checked
from deckcheck.includes import resolve_tree
from deckcheck.index import build

TORTURE = Path(__file__).parent / "torture"


def run(case):
    tree = resolve_tree(TORTURE / case / "main.k")
    return tree, build(tree)


def whats(items):
    return [n.what for n in items]


def test_clean_deck_lists_only_the_dc005_scope_line():
    tree, ix = run("base")
    assert whats(not_checked(tree, ix)) == ["unused definitions of other kinds (DC005)"]


def test_unfollowed_include_blinds_all_references(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE_AUTO_OFFSET\nx.k\n*END\n", encoding="latin-1")
    tree = resolve_tree(tmp_path / "main.k")
    items = not_checked(tree, build(tree))
    assert items[0].what == "all references (DC001, DC006)" and items[0].count == 1
    assert set(dc005_silent(tree, build(tree))) == set(DC005_KINDS)


def test_unknown_parameter_makes_mat_uses_uncertain(tmp_path):
    body = ("*PART\nplate\n" + f"{1:>10}{1:>10}{'&nope':>10}" + "\n*SECTION_SHELL\n" + f"{1:>10}{2:>10}" + "\n"
            + f"{1.0:>10}" * 4 + "\n*MAT_ELASTIC\n" + f"{1:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n")
    (tmp_path / "main.k").write_text("*KEYWORD\n" + body + "*END\n", encoding="latin-1")
    tree = resolve_tree(tmp_path / "main.k")
    silent = dc005_silent(tree, build(tree))
    assert "MAT" in silent and silent["MAT"].startswith("main.k:")
    assert "unused MAT (DC005)" in whats(not_checked(tree, build(tree)))


def test_unknown_keyword_silences_dc005(tmp_path):
    (tmp_path / "main.k").write_text("*KEYWORD\n*NOT_A_REAL_KEYWORD\n1\n*END\n", encoding="latin-1")
    tree = resolve_tree(tmp_path / "main.k")
    assert "NOT_A_REAL_KEYWORD" in dc005_silent(tree, build(tree))["MAT"]
    assert "keywords deckcheck doesn't know (passed through)" in whats(not_checked(tree, build(tree)))
```

Run: `.venv/Scripts/python -m pytest tests/test_coverage.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.coverage'`.

`*INCLUDE_AUTO_OFFSET` is used here as an include the resolver doesn't follow. First confirm, in
`src/deckcheck/includes.py:143`, that this keyword produces an `unfollowed` problem. If it doesn't, use any
`*INCLUDE_*` variant that does.

- [ ] **Step 7: Implement coverage**

`src/deckcheck/coverage.py`:

```python
"""What deckcheck could not check in a run, and why (spec §5: never a diagnostic; §6: the "Not checked" footer)."""
import functools
import tomllib
from importlib import resources

from deckcheck.diagnostics import NotChecked
from deckcheck.includes import Tree
from deckcheck.index import STRUCTURAL, Index

DC005_KINDS = ("MAT", "SECTION", "HOURGLASS")  # spec §5: the kinds whose every referring field is audited
SHOWN = 3


@functools.cache
def dc005_audit() -> list[dict]:
    text = resources.files("deckcheck.data").joinpath("dc005_audit.toml").read_text(encoding="utf-8")
    return tomllib.loads(text).get("field", [])


def unknown_keywords(tree: Tree) -> list[tuple[str, str]]:
    """(file:line, name) of every block the keyword data doesn't cover: it passes through unchecked (spec §4)."""
    return [(f"{node.path.name}:{b.line}", b.name) for node in tree.files for b in node.source.blocks
            if b.resolved is None and b.name not in STRUCTURAL and not b.name.startswith(("INCLUDE", "PARAMETER"))]


def dc005_silent(tree: Tree, ix: Index) -> dict[str, str]:
    """Kinds DC005 must stay silent on, each with the first reason: a use deckcheck can't see would make a used
    definition look unused."""
    why: dict[str, str] = {}
    unknown = unknown_keywords(tree)
    present = {b.resolved.name for node in tree.files for b in node.source.blocks if b.resolved}
    for kind in DC005_KINDS:
        if ix.blind:
            why[kind] = sorted(ix.blind)[0]
        elif ix.failures:
            fi, line, text = ix.failures[0]
            why[kind] = f"{tree.files[fi].path.name}:{line} {text}"
        elif kind in ix.uncertain_uses:
            why[kind] = sorted(ix.uncertain_uses[kind])[0]
        elif kind in ix.uncertain_defs:
            why[kind] = sorted(ix.uncertain_defs[kind])[0]
        elif unknown:
            where, name = unknown[0]
            why[kind] = f"{where} *{name}: a keyword deckcheck doesn't know may refer to it"
        else:
            for entry in dc005_audit():
                if entry["kind"] == kind and entry["verdict"] == "undecided" and entry["keyword"] in present:
                    why[kind] = f"*{entry['keyword']} {entry['field']} may refer to it (not yet audited)"
                    break
    return why


def _item(what: str, reasons: list[str]) -> NotChecked:
    return NotChecked(what, tuple(reasons[:SHOWN]), len(reasons))


def not_checked(tree: Tree, ix: Index) -> list[NotChecked]:
    out = []
    if ix.blind:
        out.append(_item("all references (DC001, DC006)", sorted(ix.blind)))
    for kind in sorted(ix.uncertain_defs):
        out.append(_item(f"references to {kind} (DC001, DC006)", sorted(ix.uncertain_defs[kind])))
    unread = [f"{tree.files[fi].path.name}:{p.line} {p.detail}" for fi, p in ix.problems if p.kind == "unread"]
    if unread:
        out.append(_item("blocks read only in part", unread))
    unknown = unknown_keywords(tree)
    if unknown:
        out.append(_item("keywords deckcheck doesn't know (passed through)", [f"{w} *{n}" for w, n in unknown]))
    for kind, why in dc005_silent(tree, ix).items():
        out.append(_item(f"unused {kind} (DC005)", [why]))
    out.append(_item("unused definitions of other kinds (DC005)", [f"checked for {', '.join(DC005_KINDS)} only"]))
    return out
```

Create `src/deckcheck/data/dc005_audit.toml` with only its header. Task 5 fills it:

```toml
# DC005 audit (spec §5, plan M1d Task 5). Every field whose name looks like a reference to MAT, SECTION or
# HOURGLASS but carries no link in the layout, outside that kind's own defining keywords, is listed here:
#   verdict = "namespace": it refers to another id space (reason says which), so it is not a use;
#   verdict = "undecided": DC005 stays silent on the kind in any deck containing this keyword.
# A field that does refer to the kind gets a link in overrides.toml instead (with evidence), not an entry here.
```

- [ ] **Step 8: Run the coverage tests and the whole suite**

Run: `.venv/Scripts/python -m pytest tests/test_coverage.py tests/test_index.py -q`
Expected: PASS.

Run: `.venv/Scripts/python -m pytest -q`
Expected: the M1c baseline (323 passed, 1 skipped, 2 xfailed) plus the new tests, all passing.

- [ ] **Step 9: Commit**

```bash
git add src/deckcheck/diagnostics.py src/deckcheck/coverage.py src/deckcheck/data/dc005_audit.toml src/deckcheck/index.py tests/test_index.py tests/test_coverage.py
git commit -m "M1d Task 2: diagnostics records, ignored references, block failures, coverage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Rules DC000, DC001, DC002, DC004, DC006 and the torture harness

**Files:**
- Create: `src/deckcheck/rules/__init__.py`, `src/deckcheck/rules/references.py`, `src/deckcheck/rules/duplicates.py`,
  `src/deckcheck/rules/include_files.py`, `src/deckcheck/rules/failures.py`, `tests/test_rules.py`
- Modify: `tests/torture/seeded_mistakes/expected.toml`, `crlf_seeded/expected.toml`,
  `latin1_seeded/expected.toml` (M0 `findings` line numbers)

**Interfaces:**
- Consumes:
  - `Index.dangling()`, `Index.duplicates()`, `Index.ignored()`, `Index.failures`, `Tree.problems` (Task 2, M1b/M1c);
  - `ACCEPTED_DUPLICATES` (Task 1 Step 3).
- Produces:
  - `deckcheck.rules.check(main: Path) -> Report`;
  - `deckcheck.rules.CODES: tuple[str, ...]`, every code, used by the CLI for `--ignore`;
  - `deckcheck.rules.RULES: list`, which Tasks 4 and 5 append DC003 and DC005 to.

- [ ] **Step 1: Write the failing harness and unit tests**

`tests/test_rules.py`:

```python
import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.rules import CODES, check

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))
IMPLEMENTED = ["DC000", "DC001", "DC002", "DC004", "DC006"]  # Task 4 adds DC003, Task 5 DC005


def expected(case: str, code: str) -> list[dict]:
    """DC001, DC002 and DC004 follow from the [index] and [resolver] tables (already refereed); the other codes are
    listed one by one in [[diagnostics]]."""
    e = tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))
    if code == "DC001":
        return [{"file": d["file"], "line": d["line"], "columns": d["columns"]} for d in e.get("index", {}).get("dangling", [])]
    if code == "DC002":
        return [{"file": d["file"], "line": d["line"], "columns": d["columns"]} for d in e.get("index", {}).get("duplicates", [])]
    if code == "DC004":
        return [{"file": p["file"], "line": p["line"]} for p in e.get("resolver", {}).get("problems", [])
                if p["kind"] in ("missing", "cycle")]
    return [{"file": d["file"], "line": d["line"], "columns": d["columns"], "severity": d["severity"]}
            for d in e.get("diagnostics", []) if d["code"] == code]


def got(case: str, code: str) -> list[dict]:
    root = Path(os.path.abspath(TORTURE / case))
    out = []
    for d in check(TORTURE / case / "main.k").diagnostics:
        if d.code != code:
            continue
        row = {"file": d.path.relative_to(root).as_posix(), "line": d.line}
        if code != "DC004":
            row["columns"] = [d.start, d.end]
        if code not in ("DC001", "DC002", "DC004"):
            row["severity"] = d.severity
        out.append(row)
    return out


@pytest.mark.parametrize("code", IMPLEMENTED)
@pytest.mark.parametrize("case", CASES)
def test_torture_diagnostics(case, code):
    assert got(case, code) == expected(case, code)


def test_codes():
    assert CODES == ("DC000", "DC001", "DC002", "DC003", "DC004", "DC005", "DC006")


def test_seeded_mistakes_messages():
    ds = {d.code: d for d in check(TORTURE / "seeded_mistakes" / "main.k").diagnostics}
    assert ds["DC004"].message == "include file 'missing_file.k' not found"
    assert ds["DC001"].message == ("*PART mid refers to MAT 99, which is not defined; "
                                   "it may be defined in missing include 'missing_file.k'")
    assert ds["DC001"].severity == "error"
    assert ds["DC002"].message.startswith("PART 1 is defined twice (first at main.k:8)")
    assert ds["DC002"].related[0].line == 8


def test_dc006_message():
    [d] = [d for d in check(TORTURE / "spc_set_none" / "main.k").diagnostics if d.code == "DC006"]
    assert d.severity == "warning"
    assert d.message == ("*BOUNDARY_SPC_SET nsid refers to SET_NODE 99, which is not defined; "
                         "LS-DYNA accepts this, but the reference has no effect")


def test_dc000_reports_block_failure(tmp_path, monkeypatch):
    import deckcheck.index as index_mod
    real = index_mod.read_fields
    monkeypatch.setattr(index_mod, "read_fields", lambda block, *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
                        if block.name == "MAT_ELASTIC" else real(block, *a, **k))
    (tmp_path / "main.k").write_bytes((TORTURE / "base" / "main.k").read_bytes())
    [d] = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC000"]
    assert d.severity == "warning" and "*MAT_ELASTIC: RuntimeError: boom" in d.message
```

In the M0 `findings` of `seeded_mistakes`, `crlf_seeded` and `latin1_seeded`, add a line
`note_m1d = "the M0 findings' line numbers come from dynars; M1d's harness reads the [index]/[resolver] tables"`.
Leave `findings` unchanged: `test_torture_layout` checks their shape only.

Add the spc case's DC006 expectation to `tests/torture/spc_set_none/expected.toml`. The `*BOUNDARY_SPC_SET` card is
line 22 and "99" sits at columns 8–10:

```toml
[[diagnostics]]
code = "DC006"
severity = "warning"
file = "main.k"
line = 22
columns = [8, 10]
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.rules'`.

- [ ] **Step 3: Implement the rules**

`src/deckcheck/rules/references.py`:

```python
"""DC001 dangling reference (error) and DC006 accepted but no effect (warning), spec §5."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index, Ref


def _what(r: Ref) -> str:
    key, field = r.field.split(".", 1)
    return f"*{key} {field} refers to {r.kind} {r.id}, which is not defined"


def dc001(tree: Tree, ix: Index) -> list[Diagnostic]:
    missing = [p.name for p in tree.problems if p.kind == "missing"]
    note = ""
    if missing:
        note = f"; it may be defined in missing include '{missing[0]}'"
        if len(missing) > 1:
            note += f" or {len(missing) - 1} other missing include(s)"
    return [Diagnostic(r.path, r.line, r.start, r.end, "error", "DC001", _what(r) + note) for r in ix.dangling()]


def dc006(tree: Tree, ix: Index) -> list[Diagnostic]:
    return [Diagnostic(r.path, r.line, r.start, r.end, "warning", "DC006",
                       _what(r) + "; LS-DYNA accepts this, but the reference has no effect") for r in ix.ignored()]
```

`src/deckcheck/rules/duplicates.py`:

```python
"""DC002 duplicate id, spec §5. Severity per kind from LS-DYNA (bakeoff/results/m1d_referee.txt, M1d Task 1):
a kind LS-DYNA rejects twice-defined is an error; one it accepts is a warning naming the definition it uses.
A kind not tested is reported as a warning that says so, never as a confirmed error."""
from deckcheck.diagnostics import Diagnostic, Related
from deckcheck.includes import Tree
from deckcheck.index import Index

REJECTED: frozenset[str] = frozenset()        # filled from m1d_referee.txt: kinds LS-DYNA rejects duplicated
ACCEPTED_DUPLICATES: dict[str, str] = {}      # filled from m1d_referee.txt: kind -> "first" | "last" | "unknown"


def dc002(tree: Tree, ix: Index) -> list[Diagnostic]:
    out = []
    for d in ix.duplicates():
        head = f"{d.kind} {d.id} is defined twice (first at {d.first_path.name}:{d.first_line})"
        related = (Related(d.first_path, d.first_line, "first definition"),)
        if d.kind in REJECTED:
            severity, message = "error", head
        elif d.kind in ACCEPTED_DUPLICATES:
            wins = ACCEPTED_DUPLICATES[d.kind]
            tail = (f"LS-DYNA accepts this and uses the {wins} definition" if wins in ("first", "last")
                    else "LS-DYNA accepts this; which definition it uses is not known")
            severity, message = "warning", f"{head}; {tail}"
        else:
            severity, message = "warning", f"{head}; not tested whether LS-DYNA rejects this"
        out.append(Diagnostic(d.path, d.line, d.start, d.end, severity, "DC002", message, related))
    return out
```

Fill `REJECTED` and `ACCEPTED_DUPLICATES` from `bakeoff/results/m1d_referee.txt`: each tested kind goes in exactly
one of them. `PART` from `m1d_dup_part` decides what `seeded_mistakes` reports. Add one more line to
`test_seeded_mistakes_messages` asserting `ds["DC002"].severity` equals the referee's answer for PART.

`src/deckcheck/rules/include_files.py`:

```python
"""DC004 include problem (error), spec §5: a missing file or a circular include, from the resolver."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index

MESSAGES = {"missing": "include file '{}' not found", "cycle": "include '{}' is circular: it includes itself"}


def dc004(tree: Tree, ix: Index) -> list[Diagnostic]:
    return [Diagnostic(p.file, p.line, p.columns[0], p.columns[1], "error", "DC004", MESSAGES[p.kind].format(p.name))
            for p in tree.problems if p.kind in MESSAGES]
```

`src/deckcheck/rules/failures.py`:

```python
"""DC000: deckcheck itself failed on a block (spec §6: one diagnostic, the run continues). Its kinds are listed
under "Not checked"; the warning asks for a report, because it is a deckcheck bug, not a deck mistake."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index


def dc000(tree: Tree, ix: Index) -> list[Diagnostic]:
    return [Diagnostic(tree.files[fi].path, line, 0, 1, "warning", "DC000",
                       f"deckcheck could not read {text}; this block is not checked (please report this)")
            for fi, line, text in ix.failures]
```

`src/deckcheck/rules/__init__.py`:

```python
"""Run every check on one main deck (spec §5). A rule is a function (tree, index) -> list[Diagnostic]; adding a
check is adding a module here and a line to RULES."""
from pathlib import Path

from deckcheck.coverage import not_checked
from deckcheck.diagnostics import Report
from deckcheck.includes import resolve_tree
from deckcheck.index import build
from deckcheck.rules.duplicates import dc002
from deckcheck.rules.failures import dc000
from deckcheck.rules.include_files import dc004
from deckcheck.rules.references import dc001, dc006

CODES = ("DC000", "DC001", "DC002", "DC003", "DC004", "DC005", "DC006")
RULES = [dc000, dc001, dc002, dc004, dc006]


def check(main: Path) -> Report:
    tree = resolve_tree(main)
    ix = build(tree)
    found = [d for rule in RULES for d in rule(tree, ix)]
    found.sort(key=lambda d: (str(d.path), d.line, d.start, d.code))
    return Report(main, found, not_checked(tree, ix))
```

- [ ] **Step 4: Run the rule tests**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -q`
Expected: PASS. If a torture case's DC001 or DC002 differs from its `[index]` table, the rule is wrong, not the
table: the tables are refereed.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/deckcheck/rules tests/test_rules.py tests/torture/seeded_mistakes/expected.toml tests/torture/crlf_seeded/expected.toml tests/torture/latin1_seeded/expected.toml tests/torture/spc_set_none/expected.toml
git commit -m "M1d Task 3: DC000, DC001, DC002, DC004, DC006 and the torture diagnostics harness

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: DC003 values and format

**Files:**
- Create: `src/deckcheck/rules/values.py`
- Modify: `src/deckcheck/rules/__init__.py` (RULES), `tests/test_rules.py` (IMPLEMENTED, unit tests),
  `tests/torture/tabs/expected.toml`, `tests/torture/m1d_overflow_node/expected.toml`,
  `tests/torture/m1d_mixed_free/expected.toml`, and any case whose DC003 output is verified real (Step 4)

**Interfaces:**
- Consumes:
  - `Index.problems: list[tuple[int, FieldProblem]]`, where `FieldProblem(kind, line, start, end, detail)` and kind
    is `"bad"`, `"extra"` or `"unread"`;
  - `Tree.files[i].source.blocks[j].cards`, a list of `Card(line, text)`;
  - Task 1's overflow and mixed-format verdicts.
- Produces: `deckcheck.rules.values.dc003(tree, ix) -> list[Diagnostic]`.

- [ ] **Step 1: Write the failing tests**

Add `"DC003"` to `IMPLEMENTED` in `tests/test_rules.py`, and append:

```python
def test_dc003_tab_is_one_warning_per_card():
    ds = [d for d in check(TORTURE / "tabs" / "main.k").diagnostics if d.code == "DC003"]
    assert [(d.line, d.start, d.end) for d in ds] == [(19, 1, 2)]
    assert ds[0].message == "tab in card: LS-DYNA misreads tab-separated cards (use spaces or commas)"


def test_dc003_bad_value(tmp_path):
    body = ("*KEYWORD\n*PART\nplate\n" + f"{1:>10}{1:>10}{'1x':>10}" + "\n*SECTION_SHELL\n" + f"{1:>10}{2:>10}"
            + "\n" + f"{1.0:>10}" * 4 + "\n*MAT_ELASTIC\n" + f"{1:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*END\n")
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    [d] = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC003"]
    assert (d.line, d.start, d.end, d.severity) == (4, 28, 30, "warning")
    assert d.message == "mid: '1x' is not int; LS-DYNA may misread this card"
```

In `tests/torture/tabs/expected.toml`, add the tab finding. Line 19 holds `1\t7.85E-9\t...`, so the first tab is at
column 1:

```toml
[[diagnostics]]
code = "DC003"
severity = "warning"
file = "main.k"
line = 19
columns = [1, 2]
```

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -q -k "dc003 or DC003"`
Expected: FAIL. No rule produces DC003 yet, and the unit tests find no diagnostic to unpack.

- [ ] **Step 2: Implement DC003**

`src/deckcheck/rules/values.py`:

```python
"""DC003 value or format problem (warning), spec §5: a value not of its field's type, a card containing a tab, cards
past a keyword's layout. Overflow and mixed format: see the M1d Task 1 verdicts recorded below."""
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index

TAB = "tab in card: LS-DYNA misreads tab-separated cards (use spaces or commas)"


def dc003(tree: Tree, ix: Index) -> list[Diagnostic]:
    out, tab_lines = [], set()
    for fi, node in enumerate(tree.files):
        for block in node.source.blocks:
            for card in block.cards:
                if "\t" in card.text:
                    i = card.text.index("\t")
                    tab_lines.add((fi, card.line))
                    out.append(Diagnostic(node.path, card.line, i, i + 1, "warning", "DC003", TAB))
    for fi, p in ix.problems:
        if (fi, p.line) in tab_lines:  # the tab is the cause: one finding per card
            continue
        if p.kind == "bad":
            out.append(Diagnostic(tree.files[fi].path, p.line, p.start, p.end, "warning", "DC003",
                                  f"{p.detail}; LS-DYNA may misread this card"))
        elif p.kind == "extra":
            out.append(Diagnostic(tree.files[fi].path, p.line, p.start, p.end, "warning", "DC003", p.detail))
    return out
```

Add `dc003` to `RULES` in `rules/__init__.py` (import from `deckcheck.rules.values`).

- [ ] **Step 3: Apply the overflow and mixed-format verdicts**

Read `m1d_overflow_node` and `m1d_mixed_free` in `bakeoff/results/m1d_referee.txt`.

- **Mixed format** (`m1d_mixed_free`). If LS-DYNA rejected the card or misread it silently, add this detector to
  `dc003`. Write its test first, and watch it fail before adding the code. The test asserts one DC003 at line 29,
  columns `[19, 38]`, the slot `"  210000.0       0.3"`. Confirm those columns by printing
  `card.text.split(",")` offsets.

  ```python
  # two values in one comma-separated slot: LS-DYNA <verdict from m1d_referee.txt> (torture m1d_mixed_free)
                  if card.free:
                      at = 0
                      for slot in card.text.split(","):
                          if len(slot.split()) > 1:
                              s = at + len(slot) - len(slot.lstrip())
                              out.append(Diagnostic(node.path, card.line, s, at + len(slot.rstrip()), "warning",
                                                    "DC003", "two values in one comma-separated field"))
                          at += len(slot) + 1
  ```
  If LS-DYNA read the card correctly, add no detector. The spec row loses "mixed format", citing the case.
- **Overflow** (`m1d_overflow_node`). Whatever the verdict, M1d adds no overflow detector. Telling a spill-over from
  two full-width values needs every field of the card read, and the index reads only linked fields. If LS-DYNA
  misread it silently, its §12 register row reads "tested, class 2, not detected yet (needs full-card field reading,
  M4)". If LS-DYNA rejected it, the row reads "tested, class 1, not detected yet (same reason)". Either way, update
  the spec §5 DC003 row to match, citing the case.

Write each case's `[[diagnostics]]` in its `expected.toml` to match what deckcheck now reports and the verdict
justifies. An empty list means deckcheck reports nothing there.

- [ ] **Step 4: Judge every DC003 on the torture cases**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -q -k DC003`
For each failing case, deckcheck reports a DC003 that `expected.toml` doesn't list. Open the card and decide.
- **The value really isn't its field's type** (a real deck mistake, or a deliberate torture quirk): add the
  `[[diagnostics]]` entry.
- **The value is fine** (a reader bug): fix the reader with a failing test first, under
  superpowers:systematic-debugging. Never edit the expectation to match a wrong output.

Ledger each decision as a ruling.

Expected after judging: PASS.

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

```bash
git add src/deckcheck/rules tests/test_rules.py tests/torture docs/specs/2026-10-27-deckcheck-design.md
git commit -m "M1d Task 4: DC003 bad values, tabs, cards past the layout; overflow and mixed-format verdicts applied

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: DC005 audit and rule

**Files:**
- Create: `src/deckcheck/rules/unused.py`, `tests/test_dc005_audit.py`
- Modify: `src/deckcheck/data/dc005_audit.toml`, `src/deckcheck/data/overrides.toml` (links found by the audit),
  `src/deckcheck/rules/__init__.py` (RULES), `tests/test_rules.py` (IMPLEMENTED),
  `tests/torture/*/expected.toml` (verified DC005 findings), spec §12 (umat row)

**Interfaces:**
- Consumes:
  - `deckcheck.coverage.DC005_KINDS`, `dc005_silent(tree, ix)` and `dc005_audit()` (Task 2);
  - `Index.used(kind) -> set[int]`;
  - `Index.defs[kind]: dict[int, int]` (id → packed location);
  - `Index.where(loc)`;
  - `deckcheck.keywords.load()`, `layout(key)` and `walk_cards(cards)`;
  - `deckcheck.definers.definers()`.
- Produces: `deckcheck.rules.unused.dc005(tree, ix) -> list[Diagnostic]`.

- [ ] **Step 1: Write the failing audit test**

`tests/test_dc005_audit.py`:

```python
"""Spec §5: DC005 reports a kind only once every field that could refer to it is linked. The name patterns are a
heuristic lower bound (docs/plans/2026-10-29-m1d-checks-cli.md, Task 5); each hit is decided by hand."""
import re

from deckcheck.coverage import DC005_KINDS, dc005_audit
from deckcheck.definers import definers
from deckcheck.keywords import layout, load, walk_cards

LOOKALIKE = {"MAT": r"^(mid|mat|mid\d+|mids|matid)$", "SECTION": r"^(secid|secid\d+)$", "HOURGLASS": r"^hgid$"}


def open_fields() -> list[tuple[str, str, str]]:
    audited = {(e["keyword"], e["field"], e["kind"]) for e in dc005_audit()}
    out = []
    for key in sorted(load()["keywords"]):
        own = {k for k, _ in definers().get(key, ())}
        for kind in DC005_KINDS:
            if kind in own:
                continue
            for card in walk_cards(layout(key)["cards"]):
                for f in card.get("fields", []):
                    if (re.match(LOOKALIKE[kind], f["name"]) and "link" not in f and "link_by" not in f
                            and (key, f["name"], kind) not in audited):
                        out.append((key, f["name"], kind))
    return out


def test_every_lookalike_field_is_linked_or_audited():
    assert open_fields() == []


def test_audit_entries_are_well_formed():
    for e in dc005_audit():
        assert e["kind"] in DC005_KINDS and e["verdict"] in ("namespace", "undecided") and e["reason"], e
```

Run: `.venv/Scripts/python -m pytest tests/test_dc005_audit.py -q`
Expected: FAIL. During planning the scan found about 25 open keywords: 23 for MAT (CESE, DUALCESE, BATTERY,
`CONTROL_IMPLICIT_MODAL_DYNAMIC_*` and others) and 2 for SECTION (`ICFD_PART`, `ICFD_PART_VOL`). HOURGLASS had
none.

- [ ] **Step 2: Decide each open field**

For each `(keyword, field, kind)` printed, decide from pydyna's field description in the extracted data, the
keyword's other fields, and corpus deck text. Use `grep -rn "^\*<KEYWORD>" .corpus` for real uses.
- **It refers to that kind's structural ids** (a `*MAT_*`, `*SECTION_*` or `*HOURGLASS` id). Add a link override
  to `overrides.toml` under `# --- References pydyna's data does not mark.`. It needs evidence: a corpus deck line
  pair, or a torture case LS-DYNA rejects when the id is missing.
- **It refers to another id space**: CESE and DUALCESE materials (`*CESE_MAT_*`), ICFD sections
  (`*ICFD_SECTION`), battery and electrochemistry ids, a mode number. Add a `[[field]]` entry with
  `verdict = "namespace"` and a reason naming that space.
- **It can't be decided cheaply.** Add `verdict = "undecided"` with the reason. DC005 then stays silent on that kind
  in any deck containing the keyword (`dc005_silent`, Task 2).

```toml
[[field]]
keyword = "CESE_PART"
field = "mid"
kind = "MAT"
verdict = "namespace"
reason = "a *CESE_MAT_* id (CESE solver materials), not a structural *MAT_*"
```

(Check that example's claim against the data before keeping it.) Ledger the count of each verdict.

Run: `.venv/Scripts/python -m pytest tests/test_dc005_audit.py -q`
Expected: PASS.

- [ ] **Step 3: Write the failing rule tests**

Add `"DC005"` to `IMPLEMENTED` in `tests/test_rules.py`, and append:

```python
def test_dc005_unused_material_in_seeded_mistakes_is_silent_because_of_missing_include():
    # the missing include could refer to MAT 7: a missing file is not a blind tree, so check what dc005_silent says
    ds = [d for d in check(TORTURE / "seeded_mistakes" / "main.k").diagnostics if d.code == "DC005"]
    assert [(d.line, d.start, d.end) for d in ds] == EXPECTED_SEEDED_DC005


def test_dc005_message(tmp_path):
    body = ((TORTURE / "base" / "main.k").read_text(encoding="latin-1").replace(
        "*END", "*MAT_ELASTIC\n" + f"{7:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*END"))
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    [d] = [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC005"]
    assert d.severity == "warning" and d.message == "MAT 7 is defined but nothing refers to it"


def test_dc005_silent_on_unknown_keyword(tmp_path):
    body = ((TORTURE / "base" / "main.k").read_text(encoding="latin-1").replace(
        "*END", "*MAT_ELASTIC\n" + f"{7:>10}{'7.85E-9':>10}{'210000.0':>10}{0.3:>10}" + "\n*NOT_A_REAL_KEYWORD\n7\n*END"))
    (tmp_path / "main.k").write_text(body, encoding="latin-1")
    assert [d for d in check(tmp_path / "main.k").diagnostics if d.code == "DC005"] == []


def test_umat_part_material_is_not_reported():
    ds = check(TORTURE / "m1d_umat" / "main.k").diagnostics
    assert not [d for d in ds if d.code in ("DC001", "DC005") and "MAT 2" in d.message]
```

A missing include does not blind the index: `test_missing_include_does_not_blind` in `test_index.py` pins that.
But a missing file could hold the only reference to MAT 7, so DC005 on `seeded_mistakes` would be a guess. Add
this to `dc005_silent` in `coverage.py` as the first check in the loop, and write its test before the code:

```python
        missing = [p for p in tree.problems if p.kind == "missing"]
        if missing:
            why[kind] = f"{missing[0].file.name}:{missing[0].line} missing include '{missing[0].name}' may refer to it"
            continue
```

So `EXPECTED_SEEDED_DC005 = []` (define it at module level in `test_rules.py`). M0's "MAT 7 unused" finding was
made without knowing what the missing file holds. Ledger this as a ruling. The `test_dc005_message` test shows the
unused material reported where nothing is missing.

`base` has the two-line base model and is used here only as a clean deck. First check that it defines MAT 1,
SECTION 1, PART 1 and no hourglass, all used: `.venv/Scripts/python -c "from deckcheck.rules import check; ..."`.

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -q -k "dc005 or DC005 or umat"`
Expected: FAIL. No rule produces DC005 yet.

- [ ] **Step 4: Implement DC005**

`src/deckcheck/rules/unused.py`:

```python
"""DC005 unused definition (warning), spec §5: a MAT, SECTION or HOURGLASS that nothing refers to. Silent on a kind
wherever a use could be invisible (deckcheck.coverage.dc005_silent); the footer says why."""
from deckcheck.coverage import DC005_KINDS, dc005_silent
from deckcheck.diagnostics import Diagnostic
from deckcheck.includes import Tree
from deckcheck.index import Index


def dc005(tree: Tree, ix: Index) -> list[Diagnostic]:
    silent = dc005_silent(tree, ix)
    out = []
    for kind in DC005_KINDS:
        if kind in silent:
            continue
        used = ix.used(kind)
        for id_, loc in sorted(ix.defs.get(kind, {}).items()):
            if id_ not in used:
                path, line, start, end = ix.where(loc)
                out.append(Diagnostic(path, line, start, end, "warning", "DC005",
                                      f"{kind} {id_} is defined but nothing refers to it"))
    return out
```

Add `dc005` to `RULES`.

- [ ] **Step 5: Judge every DC005 on the torture cases**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -q -k DC005`
For each case where deckcheck reports a DC005 that `expected.toml` doesn't list, search the case's files for the
id. If the id appears nowhere else (outside comments), it's a true finding: add the `[[diagnostics]]` entry. If the
id appears in a field that refers to the kind, that's a missing link: fix it with an override and evidence, never
by editing the expectation. `m1d_mixed_free` defines MAT 2 and nothing uses it, so expect a DC005 there.

Expected after judging: PASS.

- [ ] **Step 6: Update the register, run the suite, commit**

In spec §12, the user-defined-material row records what `m1d_umat` showed: read, or not checked, with LS-DYNA's
verdict.

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

```bash
git add src/deckcheck/rules src/deckcheck/coverage.py src/deckcheck/data tests docs/specs/2026-10-27-deckcheck-design.md
git commit -m "M1d Task 5: DC005 for MAT, SECTION, HOURGLASS with the linked-field audit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Command line, text and JSON

**Files:**
- Create: `src/deckcheck/cli.py`, `src/deckcheck/__main__.py`, `tests/test_cli.py`
- Modify: `pyproject.toml` (`[project.scripts]`, version `0.1.0`), `src/deckcheck/__init__.py` (version `0.1.0`)

**Interfaces:**
- Consumes: `deckcheck.rules.check(main) -> Report` and `deckcheck.rules.CODES` (Task 3).
- Produces: `deckcheck.cli.main(argv: list[str] | None = None) -> int`, the `deckcheck` console command, and
  `python -m deckcheck`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deckcheck.cli import main

TORTURE = Path(__file__).parent / "torture"
SEEDED = TORTURE / "seeded_mistakes" / "main.k"


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_text_output_and_exit_1(capsys, monkeypatch):
    monkeypatch.chdir(TORTURE)
    code, out, _ = run(capsys, "seeded_mistakes/main.k")
    lines = out.splitlines()
    assert code == 1
    assert lines[0] == "seeded_mistakes/main.k:3:1  error    DC004  include file 'missing_file.k' not found"
    assert any(l.startswith("seeded_mistakes/main.k:8:29  error    DC001  *PART mid refers to MAT 99") for l in lines)
    assert "Not checked:" in lines
    assert any(l.startswith("  unused MAT (DC005): main.k:3 missing include") for l in lines)


def test_summary_counts(capsys):
    from deckcheck.rules import check
    ds = check(SEEDED).diagnostics
    e, w = sum(d.severity == "error" for d in ds), sum(d.severity == "warning" for d in ds)
    word = lambda n, s: f"{n} {s}{'' if n == 1 else 's'}"
    _, out, _ = run(capsys, SEEDED)
    assert f"{word(e + w, 'problem')} ({word(e, 'error')}, {word(w, 'warning')})" in out.splitlines()


def test_clean_deck_exit_0(capsys):
    code, out, _ = run(capsys, TORTURE / "base" / "main.k")
    assert code == 0 and out.startswith("No problems found")


def test_json_output(capsys):
    code, out, _ = run(capsys, "--format", "json", SEEDED)
    data = json.loads(out)
    assert code == 1 and data["version"] == 1
    d = [d for d in data["diagnostics"] if d["code"] == "DC001"][0]
    assert (d["line"], d["column"], d["end_column"], d["severity"]) == (8, 29, 31, "error")
    assert set(d) == {"file", "line", "column", "end_column", "severity", "code", "message", "related"}
    dup = [d for d in data["diagnostics"] if d["code"] == "DC002"][0]
    assert dup["related"] == [{"file": dup["file"], "line": 8, "message": "first definition"}]
    assert data["summary"] == {"errors": sum(d["severity"] == "error" for d in data["diagnostics"]),
                               "warnings": sum(d["severity"] == "warning" for d in data["diagnostics"])}
    assert {"main", "what", "reasons", "count"} == set(data["not_checked"][0])


def test_ignore_codes(capsys):
    code, out, _ = run(capsys, "--format", "json", "--ignore", "dc001", "--ignore", "DC002", "--ignore", "DC004", SEEDED)
    assert code == 0 and not [d for d in json.loads(out)["diagnostics"] if d["severity"] == "error"]
    with pytest.raises(SystemExit) as e:
        main(["--ignore", "DC999", str(SEEDED)])
    assert e.value.code == 2
    assert "DC999" in capsys.readouterr().err


def test_missing_or_folder_main_exits_2(capsys, tmp_path):
    code, out, err = run(capsys, tmp_path / "nope.k")
    assert code == 2 and out == "" and "nope.k" in err and "Traceback" not in err
    code, _, err = run(capsys, tmp_path)
    assert code == 2 and "Traceback" not in err


def test_path_on_another_drive_prints_absolute(capsys, monkeypatch):
    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")
    monkeypatch.setattr("deckcheck.cli.os.path.relpath", other_drive)
    _, out, _ = run(capsys, SEEDED)
    assert out.splitlines()[0].startswith(Path(os.path.abspath(SEEDED)).as_posix() + ":3:1")


def test_unencodable_path_does_not_crash(tmp_path):
    folder = tmp_path / "モデル"
    folder.mkdir()
    (folder / "main.k").write_text("*KEYWORD\n*INCLUDE\nmissing.k\n*END\n", encoding="latin-1")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run([sys.executable, "-m", "deckcheck", str(folder / "main.k")], capture_output=True, env=env)
    assert proc.returncode == 1 and b"Traceback" not in proc.stderr and b"DC004" in proc.stdout


def test_two_main_decks(capsys):
    code, out, _ = run(capsys, "--format", "json", SEEDED, TORTURE / "base" / "main.k")
    data = json.loads(out)
    assert code == 1 and len({n["main"] for n in data["not_checked"]}) == 2  # each main deck has its own footer
```

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.cli'`.

- [ ] **Step 2: Implement the CLI**

`src/deckcheck/cli.py`:

```python
"""The command line (spec §6): deckcheck MAIN.k [MAIN2.k ...] [--format text|json] [--ignore CODE ...].
Formats reports; contains no checking logic. Exit 0: no errors; 1: an error; 2: could not run."""
import argparse
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from deckcheck.diagnostics import Report
from deckcheck.rules import CODES, check


def _version() -> str:
    try:
        return version("deckcheck")
    except PackageNotFoundError:
        return "unknown"


def _rel(path: Path) -> str:
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:  # another drive on Windows: relpath has no answer
        return Path(os.path.abspath(path)).as_posix()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _text(reports: list[Report]) -> str:
    lines = []
    for r in reports:
        for d in r.diagnostics:
            lines.append(f"{_rel(d.path)}:{d.line}:{d.start + 1}  {d.severity:<7}  {d.code}  {d.message}")
    errors = sum(d.severity == "error" for r in reports for d in r.diagnostics)
    warnings = sum(d.severity == "warning" for r in reports for d in r.diagnostics)
    if lines:
        lines += ["", f"{_plural(errors + warnings, 'problem')} ({_plural(errors, 'error')}, {_plural(warnings, 'warning')})"]
    else:
        lines.append("No problems found")
    for r in reports:
        head = "Not checked:" if len(reports) == 1 else f"Not checked ({_rel(r.main)}):"
        lines += ["", head]
        for n in r.not_checked:
            more = f" (+{n.count - len(n.reasons)} more)" if n.count > len(n.reasons) else ""
            lines.append(f"  {n.what}: {'; '.join(n.reasons)}{more}")
    return "\n".join(lines) + "\n"


def _json(reports: list[Report]) -> str:
    diags = [d for r in reports for d in r.diagnostics]
    return json.dumps({
        "version": 1,
        "diagnostics": [{"file": _rel(d.path), "line": d.line, "column": d.start + 1, "end_column": d.end + 1,
                         "severity": d.severity, "code": d.code, "message": d.message,
                         "related": [{"file": _rel(x.path), "line": x.line, "message": x.message} for x in d.related]}
                        for d in diags],
        "not_checked": [{"main": _rel(r.main), "what": n.what, "reasons": list(n.reasons), "count": n.count}
                        for r in reports for n in r.not_checked],
        "summary": {"errors": sum(d.severity == "error" for d in diags),
                    "warnings": sum(d.severity == "warning" for d in diags)},
    }, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deckcheck", description="Check keyword decks for LS-DYNA for structural "
                                     "mistakes: dangling references, duplicate ids, bad values, include problems.")
    parser.add_argument("decks", nargs="+", type=Path, metavar="MAIN.k", help="main deck; includes are followed")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--ignore", action="append", default=[], metavar="CODE", help="leave out a code (repeatable)")
    parser.add_argument("--version", action="version", version=f"deckcheck {_version()}")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # a path the console can't encode must not crash the run
    args = parser.parse_args(argv)
    ignore = {c.upper() for c in args.ignore}
    unknown = sorted(ignore - set(CODES))
    if unknown:
        parser.error(f"unknown code {unknown[0]} (known: {', '.join(CODES)})")
    for deck in args.decks:
        if not deck.is_file():
            print(f"deckcheck: {deck}: no such file", file=sys.stderr)
            return 2
    try:
        reports = [check(deck) for deck in args.decks]
    except Exception as e:  # outside any one block: deckcheck could not run (spec §6)
        print(f"deckcheck: internal error: {type(e).__name__}: {e} (please report this)", file=sys.stderr)
        return 2
    for r in reports:
        r.diagnostics[:] = [d for d in r.diagnostics if d.code not in ignore]
    sys.stdout.write(_json(reports) if args.format == "json" else _text(reports))
    return 1 if any(d.severity == "error" for r in reports for d in r.diagnostics) else 0
```

`src/deckcheck/__main__.py`:

```python
import sys

from deckcheck.cli import main

sys.exit(main())
```

In `pyproject.toml`, set `version = "0.1.0"` and add:

```toml
[project.scripts]
deckcheck = "deckcheck.cli:main"
```

Set `__version__ = "0.1.0"` in `src/deckcheck/__init__.py`. Reinstall the editable package so the script exists:
`.venv/Scripts/python -m pip install -e . --no-deps`.

- [ ] **Step 3: Run the CLI tests**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q`
Expected: PASS. If `test_text_output_and_exit_1`'s footer line differs, `dc005_silent`'s reason text from Task 5 is
the source of truth: adjust the test's expected text to it, not the code.

- [ ] **Step 4: Try it by hand**

Run:
```
.venv/Scripts/deckcheck tests/torture/seeded_mistakes/main.k; echo "exit $?"
.venv/Scripts/deckcheck --format json tests/torture/spc_set_none/main.k
```
Expected: the text layout and footer as in the spec §6 example, `exit 1`, and the JSON shown with a DC006 entry.
Read the output as an engineer would. A message that's unclear is a finding: fix the wording in its rule and its
test.

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

```bash
git add src/deckcheck/cli.py src/deckcheck/__main__.py src/deckcheck/__init__.py pyproject.toml tests/test_cli.py
git commit -m "M1d Task 6: deckcheck command, text and JSON output, exit codes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Corpus gate through the real checks

**Files:**
- Create: `bakeoff/lint_tree.py`, `bakeoff/m1d_corpus.py`, `bakeoff/m1d_unused_evidence.py`,
  `bakeoff/results/m1d_lint.jsonl`, `tests/corpus/expected_diagnostics.toml`, `tests/test_rules_corpus.py`
- Modify: overrides or reader code only through failing tests, if the gate finds a false alarm

**Interfaces:**
- Consumes:
  - `deckcheck.rules.check` (Task 3);
  - `bakeoff.run.run_one(deck, cap_mb, timeout_s, module)`, which runs `python -m <module> <deck> <out.json>` under
    the cap;
  - `bakeoff.corpus.fetch` and `load_manifest`.
- Produces: the gate result, counts per code per deck, and the judged expected findings.

- [ ] **Step 1: Write the child runner and the corpus runner**

`bakeoff/lint_tree.py`:

```python
"""Run deckcheck's checks on one deck and write a summary JSON: python -m bakeoff.lint_tree <deck> <out>."""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from deckcheck.rules import check

deck, out = Path(sys.argv[1]), Path(sys.argv[2])
start = time.monotonic()
report = check(deck)
root = os.path.dirname(os.path.abspath(deck))


def rel(p):
    return Path(os.path.relpath(p, root)).as_posix()


out.write_text(json.dumps({
    "deck": str(deck),
    "counts": dict(Counter(d.code for d in report.diagnostics)),
    "diagnostics": [{"code": d.code, "severity": d.severity, "file": rel(d.path), "line": d.line}
                    for d in report.diagnostics[:200]],
    "not_checked": [{"what": n.what, "reasons": list(n.reasons), "count": n.count} for n in report.not_checked],
    "seconds": round(time.monotonic() - start, 1),
}), encoding="utf-8")
```

There's no `message` field: DC003 messages quote field values, which are deck text. Codes, files and lines keep the
results file within the corpus terms. The `not_checked` reasons hold file names, line numbers and keyword names
only. Check one VIVA+ row before committing.

`bakeoff/m1d_corpus.py`:

```python
"""M1d corpus run: deckcheck's checks on every deck, each in a child process under 2 GB."""
import json
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST, TORTURE, run_one

OUT = Path("bakeoff/results/m1d_lint.jsonl")

if __name__ == "__main__":
    decks = [(p.parent.name, p) for p in sorted(TORTURE.glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(MANIFEST)]
    with open(OUT, "w", encoding="utf-8") as f:
        for name, deck in decks:
            row = {"name": name, **run_one(deck, cap_mb=2048, timeout_s=900, module="bakeoff.lint_tree")}
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(name, row.get("error") or row["counts"], row["peak_mb"], row.get("seconds"))
```

`bakeoff/m1d_unused_evidence.py`:

```python
"""Verify a DC005 finding by text (spec §8): list every non-comment line in the deck's include tree, other than the
definition, where the id appears as a whole token. python -m bakeoff.m1d_unused_evidence <deck> <id> <def file:line>"""
import re
import sys
from pathlib import Path

from deckcheck.includes import resolve_tree

deck, id_, at = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
token = re.compile(rf"(?<![\w.+-]){re.escape(id_)}(?![\w.])")
hits = 0
for node in resolve_tree(deck).files:
    for n, line in enumerate(node.path.read_bytes().decode("latin-1").split("\n"), 1):
        if line.startswith(("$", "*")) or f"{node.path.name}:{n}" == at:
            continue
        if token.search(line):
            hits += 1
            if hits <= 20:
                print(f"{node.path.name}:{n}: {line.rstrip()[:100]}")
print(f"{hits} other line(s) contain {id_}")
```

The evidence script prints deck lines to the terminal for judging only. They are never written to a results file.

- [ ] **Step 2: Run the corpus**

Run: `.venv/Scripts/python -m bakeoff.m1d_corpus` (in the background; the Yaris takes about 60 s).
Expected:
- every deck finishes under 2 GB, with no `error` rows;
- DC001 and DC002 counts equal M1c's index findings (`tests/corpus/expected_index.toml`: only tensile_test, 632
  DC001 on PART 1);
- the VIVA+ and Yaris peaks are near M1c's (548 MB and about 1,150 MB).

- [ ] **Step 3: Judge every DC003, DC004, DC005 and DC006 finding**

For each deck and code with findings in `m1d_lint.jsonl`:
- **DC004.** It must match M1b's six real missing includes on tier 1 (`docs/m1b-reader-includes.md`).
- **DC003.** Open the line. Real (the value isn't its field's type): record it. Not real: a reader bug, fixed with
  a failing torture or unit test first.
- **DC005.** Run `python -m bakeoff.m1d_unused_evidence <deck> <id> <file:line>`. With 0 other lines, it's
  confirmed unused: record it. With other lines, read each one. A field that refers to the kind is a missing link,
  so this is a false alarm: fix it with an override plus evidence, and the Task 5 audit test must still pass. A
  coincidence (the same number as a node id, or in a title) is recorded as confirmed, with the coincidence named.
- **DC006.** Check the keyword and id in the deck text: the set must really be undefined. Record it.

Write the judged findings into `tests/corpus/expected_diagnostics.toml`:

```toml
# Corpus findings for DC003-DC006 judged real (M1d Task 7). Each cites its evidence. A deck not listed has none.
# DC001/DC002 are judged in expected_index.toml. `counts` is used where findings are many and identical.

[[deck]]
name = "<manifest name>"
findings = [{code = "DC005", file = "<file>", line = <n>}]
evidence = "<e.g. m1d_unused_evidence: 0 other lines contain 7>"
```

- [ ] **Step 4: Write the corpus test**

`tests/test_rules_corpus.py`:

```python
import tomllib
from pathlib import Path

import pytest

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST
from deckcheck.rules import check

pytestmark = pytest.mark.corpus
EXPECTED = {d["name"]: d for d in tomllib.loads(
    (Path(__file__).parent / "corpus" / "expected_diagnostics.toml").read_text(encoding="utf-8"))["deck"]}
SMALL = [e for e in load_manifest(MANIFEST) if e.tier == 1]
JUDGED_HERE = ("DC003", "DC004", "DC005", "DC006")


@pytest.mark.parametrize("entry", SMALL, ids=lambda e: e.name)
def test_tier1_diagnostics_match_judged_findings(entry):
    got = [(d.code, d.path.name, d.line) for d in check(fetch(entry)).diagnostics if d.code in JUDGED_HERE]
    want = [(f["code"], f["file"], f["line"]) for f in EXPECTED.get(entry.name, {}).get("findings", [])]
    assert got == want
    assert not [d for d in check(fetch(entry)).diagnostics if d.code == "DC000"]
```

If `tests/corpus/expected_diagnostics.toml` would otherwise have no `[[deck]]` at all, give it one entry for a deck
with no findings (`findings = []`), so `["deck"]` exists.

Run: `.venv/Scripts/python -m pytest tests/test_rules_corpus.py -q`
Expected: PASS.

- [ ] **Step 5: Rerun the corpus after any fix and commit**

If Step 3 changed code or overrides, rerun Step 2 and confirm that only the judged findings remain. Then run:
`.venv/Scripts/python -m pytest -q`
Expected: all pass.

```bash
git add bakeoff/lint_tree.py bakeoff/m1d_corpus.py bakeoff/m1d_unused_evidence.py bakeoff/results/m1d_lint.jsonl tests/corpus/expected_diagnostics.toml tests/test_rules_corpus.py src
git commit -m "M1d Task 7: corpus gate through the checks; judged findings recorded

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Clean install, README, report

**Files:**
- Create: `tests/test_install.py`, `docs/m1d-checks-cli.md`
- Modify: `README.md`, `pyproject.toml` (the `install` marker), `docs/specs/2026-10-27-deckcheck-design.md` (§11
  progress, DC000 note in §5)

**Interfaces:**
- Consumes: the `deckcheck` console command (Task 6).
- Produces: a verified wheel and the user-facing documentation.

- [ ] **Step 1: Write the failing install test**

`tests/test_install.py`:

```python
"""Spec §11: pip install works from a clean environment with no runtime dependencies."""
import subprocess
import sys
import venv
from pathlib import Path

import pytest

pytestmark = pytest.mark.install
ROOT = Path(__file__).parent.parent


def test_wheel_installs_clean_and_runs(tmp_path):
    dist = tmp_path / "dist"
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(dist)], check=True,
                   capture_output=True)
    [wheel] = dist.glob("deckcheck-0.1.0-*.whl")
    env_dir = tmp_path / "clean"
    venv.create(env_dir, with_pip=True)
    py = env_dir / "Scripts" / "python.exe"
    subprocess.run([str(py), "-m", "pip", "install", "--no-index", str(wheel)], check=True, capture_output=True)
    listed = subprocess.run([str(py), "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True).stdout
    assert {line.split("==")[0] for line in listed.split()} <= {"deckcheck", "pip", "setuptools"}
    run = subprocess.run([str(env_dir / "Scripts" / "deckcheck.exe"), str(ROOT / "tests/torture/seeded_mistakes/main.k")],
                         capture_output=True, text=True)
    assert run.returncode == 1 and "DC004" in run.stdout and "Traceback" not in run.stderr
    import zipfile
    names = zipfile.ZipFile(wheel).namelist()
    for needed in ("deckcheck/data/keywords.json", "deckcheck/data/overrides.toml", "deckcheck/data/definers.toml",
                   "deckcheck/data/dc005_audit.toml", "deckcheck/NOTICE"):
        assert needed in names, needed
    assert any(n.endswith("licenses/LICENSE") or n.endswith("/LICENSE") for n in names)
```

Add `"install: builds a wheel and a fresh venv (slow, needs hatchling from PyPI)"` to the pytest `markers` in
`pyproject.toml`.

Run: `.venv/Scripts/python -m pytest tests/test_install.py -q`
Expected: it fails or passes for a reason you can name. If it passes immediately, Task 6's packaging already
satisfies it: record that in the ledger and confirm each assertion did run (add `-rA`). If it fails on a missing
data file or LICENSE, fix `pyproject.toml`'s hatch build config (`force-include` as for NOTICE) and rerun.

- [ ] **Step 2: Write the README**

Replace `README.md` with these sections, in this order, in plain words:
1. **What it is.** "deckcheck checks keyword decks for LS-DYNA before you run them." One line on the six checks.
   One line that it never runs the solver and makes no physics judgments. Never use "LS-DYNA" as a brand: the name
   is deckcheck.
2. **Install.** `pip install deckcheck`, labelled "after the first release". Until then: `pip install .` from a
   clone.
3. **Usage:**
   - `deckcheck model.k`, with the text example taken from Task 6 Step 4's real output on `seeded_mistakes`;
   - `--format json`, with a trimmed real JSON example;
   - `--ignore`;
   - the exit codes 0/1/2 and a CI snippet: `deckcheck model.k || exit 1`.
4. **The checks.** A table of DC000–DC006, with severity and one plain sentence each, and the three classes of
   finding from spec §5.
5. **"Not checked."** What the footer means. Why deckcheck stays silent instead of guessing (no false alarms).
6. **Known limits:**
   - no physics checks;
   - `LONG=Y` long-format blocks are listed as not checked;
   - DC005 covers MAT, SECTION and HOURGLASS only;
   - DC003 checks values only in keywords that define or refer to ids;
   - results on models too large for LS-DYNA Student aren't refereed.
7. **License and credits.** Apache-2.0. The keyword data is extracted from pydyna (`ansys-dyna-core`, MIT); see
   NOTICE.

Every example output in the README is pasted from a real run, never typed.

- [ ] **Step 3: Write the M1d report and update the spec**

`docs/m1d-checks-cli.md`, with the section structure of `docs/m1c-field-reader-index.md`:
1. **LS-DYNA table**, Task 1's verdicts: case, question, verdict, deciding line, consequence.
2. **DC005 audit**: counts per verdict, the overrides added, and the undecided keywords.
3. **Corpus gate**: per tier, counts per code, peak memory and time; every judged finding cited by its evidence.
4. **Spec §11 checklist**: each M1 criterion with its evidence (test name or results file).
5. **What this means for M2**: the language server consumes `Report` directly; JSON `version` 1 is the contract.

In the spec:
- §5: add the DC000 row (a warning: deckcheck could not read a block; please report it).
- §11: replace the M1 progress note with "M1d done", plus a pointer to the report.
- §12: check that every row's status is current.

- [ ] **Step 4: Run everything and commit**

Run: `.venv/Scripts/python -m pytest -q` and then `.venv/Scripts/python -m pytest -q -m "install or corpus"`.
Expected: all pass.

```bash
git add tests/test_install.py README.md docs/m1d-checks-cli.md docs/specs/2026-10-27-deckcheck-design.md pyproject.toml
git commit -m "M1d Task 8: clean-install test, README, M1d report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

PyPI publishing and a GitHub repository are not part of this task. They wait for Chintan's explicit yes.
