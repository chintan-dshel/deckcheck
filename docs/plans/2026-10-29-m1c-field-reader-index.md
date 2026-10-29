# M1c: Field reader and index — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read every field of every block a deck uses, the way LS-DYNA lays it out. Collect each entity's definitions
and references across the include tree, ready for DC001–DC005 in M1d. On every deck LS-DYNA accepts, every
reference must resolve or be explained.

**Architecture:**
- **Extraction v2.** `tools/extract_keyword_data.py` also records each card's condition (`when`) and repeat count
  (`length`) as pydyna source text, and each field's `default`.
- **Conditions.** `deckcheck.conditions` evaluates those texts with a whitelisted `ast` evaluator: no pydyna and no
  `eval`. It answers `UNKNOWN` when it can't decide.
- **Layout.** `deckcheck.keywords.layout(key)` is the keyword's data entry with every override applied: link facts
  on fields, the `DEFINE_TABLE` row layout, and added option cards.
- **Field reader.** `deckcheck.fields.read_fields(block, ...)` walks the layout in LS-DYNA's reading order:
  - option cards, pre (descending), main, post;
  - tables, table groups and series;
  - card sets.

  It yields `Field`s (name, line, column span, parsed value, layout entry). Where it can't decide a condition or a
  length, it stops and records the rest of the block as `unread`; it never guesses. It handles free (comma) format,
  long format, and `*PARAMETER` substitution through `deckcheck.params`.
- **Index.** `deckcheck.index.build(tree)` records each entity kind's definitions (through `data/definers.toml`)
  and references (through the layout's links).
  - It applies `*INCLUDE_TRANSFORM` offsets, the "0 or blank is no reference" rule and sign rules.
  - It marks a kind **uncertain** wherever deckcheck can't see all of its definitions or uses: an unresolved
    definer, an unread region, an unknown parameter, unrefereed offsets, or an unfollowed include. M1d's rules
    stay silent on uncertain kinds.
- **LS-DYNA decides every reading rule this plan adds** (Task 1), as it did in M1b.

**Tech Stack:** Python 3.12, stdlib only at runtime (`ast`, `array`, `tomllib`). pytest. LS-DYNA R16.1 Student as
referee (`bakeoff/lsdyna_oracle.py`). `.venv-extract` (ansys-dyna-core 0.12.1) for the extraction only. psutil for
the capped corpus run.

**Spec:** `docs/specs/2026-10-27-deckcheck-design.md` (B1′). These sections bind this plan:
- §2 (meaning only from data);
- §4 (field reader and index rows, error handling: an uncovered keyword passes through, DC001 only for covered
  kinds);
- §8;
- §11 (M1 done: the M0 defects as ordinary tests, exact line and span, zero unexplained on the corpus under 2 GB).

Also binding: `docs/m1a-keyword-data.md` §4 (definer table, conditional cards, type-dependent links, ICFD namespace,
"0 or blank", offsets) and `docs/m1b-reader-includes.md` §4 (items 1–8).

**Scope split (decided with Chintan 2026-10-29):** M1c ends at the index and its corpus gate. M1d builds
DC001–DC005, diagnostics, the CLI, JSON output, the README and the clean `pip install` check on top of it.

## Global Constraints

- deckcheck has **no runtime dependencies** (spec §9). pydyna is used only by `tools/` in `.venv-extract`; psutil
  only by `bakeoff`.
- **Every reading rule comes from an LS-DYNA run or from pydyna's own reader code**, never from memory of the
  manual. Each rule constant names the case or the pydyna source that set it.
- **When deckcheck can't decide, it says so** (`unread`, `UNKNOWN`, uncertain kind). It never substitutes a guess
  that could produce a false alarm. Spec §3 gap: zero false alarms.
- External decks are never committed. Results files hold names, counts, ids and line numbers only.
- Corpus runs use a **2 GB** memory cap, each deck in a child process (process-tree RSS).
- Lines are 1-based. A column is a 0-based byte offset (Latin-1) and a span is `[start, end)`.
- No GitHub remote, no PyPI publish.
- Work on branch `m1c`, never on `main`. Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A blank line inside a table or list** (a `*NODE` block, a `*SET_PART_LIST`), as pre-processors write.
   Expected: no definition or reference from it, no `extra` problem, and the line numbers of later rows stay exact.
   Pinned by `test_blank_row_in_table` (Task 4).
2. **A short free-format card**, such as `1,2` on a card of eight fields. Expected: the missing fields are blank, not
   `bad`, and the spans of the given ones are exact. Pinned by `test_free_card_short` (Task 4).
3. **A value filling its whole fixed field**, such as `1234567890` in a 10-wide id. Expected: it reads as one value,
   with span `[0, 10)`. Pinned by `test_full_width_value` (Task 4).
4. **One file included twice under different transforms.** Expected: its ids land in two ranges, so there are no
   duplicates. Pinned by `test_same_file_two_transforms` (Task 6), where the offset is refereed.
5. **Location packing at the edges:** a long free-format card past column 1023, a line past 2**20, and file
   index 0. Expected: `unpack(pack(...))` round-trips. Pinned by `test_pack_roundtrip` (Task 6).

---

### Task 1: Ask LS-DYNA the M1c reading rules

**Files:**
- Create: `tests/torture/make_m1c_cases.py`, 15 case folders (listed in Step 1), `bakeoff/m1c_probes.py`,
  `bakeoff/results/m1c_referee.txt`, `bakeoff/results/m1c_probes.json`
- Modify: `tests/test_torture_layout.py` (case list)

**Interfaces:**
- Consumes: `bakeoff.lsdyna_oracle.lsdyna_reads(case_dir, timeout_s=120) -> tuple[bool, str]`;
  `bakeoff/referee_cases.py <case>...`.
- Produces:
  - Each case's `expected.toml`: `lsdyna_valid`, `findings = []`, `note` (question, verdict, deciding line). For a
    rejected case, an `[index]` table locates by hand what LS-DYNA complained about:
    `dangling = [{kind, id, file, line, columns = [start, end]}]` and optionally `duplicates` in the same shape.
    Task 6 tests the index against these tables.
  - `bakeoff/results/m1c_probes.json`: `{"offsets": {kind: {"control": bool, "accepted": [field...],
    "decided": field | null}}, "inc_absolute": bool}`. Task 6 copies `decided` into `index.OFFSET_FIELD`.

- [ ] **Step 1: Write the case generator**

Create `tests/torture/make_m1c_cases.py`:

```python
"""Write the M1c torture cases. Each asks LS-DYNA one question about how it reads fields. Run once; output is
committed. LS-DYNA's answers go into each case's expected.toml (M1c plan, Task 1)."""
from pathlib import Path

HERE = Path(__file__).parent


def i10(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def i20(*vals) -> str:
    return "".join(f"{v:>20}" for v in vals)


HEAD = "*KEYWORD\n*TITLE\ndeckcheck torture: {}\n*CONTROL_TERMINATION\n    1.0E-6\n"
PART = "*PART\nplate\n" + i10(1, 1, 1) + "\n"
SECTION = "*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
MAT = "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n"
MESH = ("*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2            10.0             0.0             0.0\n"
        "       3            10.0            10.0             0.0\n"
        "       4             0.0            10.0             0.0\n"
        "*ELEMENT_SHELL\n"
        "       1       1       1       2       3       4\n")
BASE = PART + SECTION + MAT + MESH
def contact(ssid: int, sstyp: int) -> str:
    return ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(ssid, 0, sstyp, 0) + "\n"
            + i10(0.0, 0.0) + "\n" + i10(1.0, 1.0) + "\n")


def velocity(id_: int, styp: int) -> str:
    return "*INITIAL_VELOCITY_GENERATION\n" + i10(id_, styp, 0.0, 0.0, 0.0, 1.0) + "\n" + i10(0.0) + "\n"



SET_PART_1 = "*SET_PART_LIST\n" + i10(1) + "\n" + i10(1) + "\n"
GOOD_MAT = "*KEYWORD\n" + MAT + "*END\n"


def deck(title: str, body: str) -> str:
    return HEAD.format(title) + body + "*END\n"


def mat24(lcss: int) -> str:  # piecewise linear plasticity, strain-rate table lcss
    return ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n" + i10(1, "7.85E-9", "210000.0", 0.3, 200.0) + "\n"
            + i10(0.0, 0.0, lcss) + "\n" + i10(*[0.0] * 8) + "\n" + i10(*[0.0] * 8) + "\n")


def curve(lcid: int) -> str:
    return "*DEFINE_CURVE\n" + i10(lcid) + "\n" + i20(0.0, 200.0) + "\n" + i20(1.0, 300.0) + "\n"


def table(rows: list[tuple[float, int]]) -> str:
    return "*DEFINE_TABLE\n" + i10(10) + "\n" + "".join(f"{v:>20}{c:>10}\n" for v, c in rows)


LONG_BASE = ("*PART\nplate\n" + i20(1, 1, 1) + "\n"
             + "*SECTION_SHELL\n" + i20(1, 2) + "\n" + i20(1.0, 1.0, 1.0, 1.0) + "\n"
             + "*MAT_ELASTIC\n" + i20(1, "7.85E-9", "210000.0", 0.3) + "\n"
             + "*NODE\n" + "".join(i20(n, x, y, 0.0) + "\n" for n, x, y in
                                   [(1, 0.0, 0.0), (2, 10.0, 0.0), (3, 10.0, 10.0), (4, 0.0, 10.0)])
             + "*ELEMENT_SHELL\n" + i20(1, 1, 1, 2, 3, 4) + "\n")

CASES = {
    "table_dangling": {  # Does LS-DYNA read DEFINE_TABLE's curve-id column (a missing id is an error)?
        "main.k": deck("table row names a missing curve",
                       BASE.replace(MAT, mat24(10)) + table([(0.0, 99), (1.0, 6)]) + curve(5) + curve(6))},
    "table_ids": {  # The same table with existing ids: the control for table_dangling
        "main.k": deck("table rows name existing curves",
                       BASE.replace(MAT, mat24(10)) + table([(0.0, 5), (1.0, 6)]) + curve(5) + curve(6))},
    "contact_type2_bad": {  # sstyp 2: is ssid a part set? (part 1 exists, part set 1 does not)
        "main.k": deck("contact type 2 without part set", BASE + contact(1, 2))},
    "contact_type3_bad": {  # sstyp 3: is ssid a part? (part set 99 exists, part 99 does not)
        "main.k": deck("contact type 3 without part", BASE + "*SET_PART_LIST\n" + i10(99) + "\n" + i10(1) + "\n"
                       + contact(99, 3))},
    "contact_type4_bad": {  # sstyp 4: is ssid a node set? (part set 1 exists, node set 1 does not)
        "main.k": deck("contact type 4 without node set", BASE + SET_PART_1 + contact(1, 4))},
    "velocity_styp1_bad": {  # styp 1: is id a part set? (part 1 exists, part set 1 does not)
        "main.k": deck("velocity styp 1 without part set", BASE + velocity(1, 1))},
    "velocity_styp3_bad": {  # styp 3: is id a node set? (part set 1 exists, node set 1 does not)
        "main.k": deck("velocity styp 3 without node set", BASE + SET_PART_1 + velocity(1, 3))},
    "inc_path_in_include": {  # Does an *INCLUDE_PATH inside an included file apply to later includes?
        "main.k": deck("include path inside an include", "*INCLUDE\nsub/a.k\n*INCLUDE\nmat.k\n"
                       + PART + SECTION + MESH),
        "sub/a.k": "*KEYWORD\n*INCLUDE_PATH\nlib\n*END\n",
        "lib/mat.k": GOOD_MAT},
    "inc_blank_in_continuation": {  # Does a blank card end a ' +' continued name, or is it skipped?
        "main.k": deck("blank card inside a continued name", "*INCLUDE\nsub/ +\n\nmat.k\n" + PART + SECTION + MESH),
        "sub/mat.k": GOOD_MAT},
    "inc_empty": {  # Is an *INCLUDE with no filename card accepted (nothing read)?
        "main.k": deck("include with no filename", "*INCLUDE\n" + BASE)},
    "long_keyword": {  # Does *KEYWORD LONG=S make every card 20 wide?
        "main.k": HEAD.format("long keyword").replace("*KEYWORD\n", "*KEYWORD LONG=S\n").replace(
            "    1.0E-6\n", i20("1.0E-6") + "\n") + LONG_BASE + "*END\n"},
    "long_section": {  # In '+' format, does an 8-field card stay on one 160-column line?
        "main.k": deck("long section card on one line",
                       BASE.replace(SECTION, "*SECTION_SHELL +\n" + i20(1, 2, 1.0, 2, 1.0, 0, 0, 1) + "\n"
                                    + i20(1.0, 1.0, 1.0, 1.0) + "\n"))},
    "parameter_ref": {  # Is &name substituted in an id field?
        "main.k": deck("parameter in an id field",
                       "*PARAMETER\nI mm               1\n" + BASE.replace(PART, "*PART\nplate\n"
                                                                            + i10(1, 1, "&mm") + "\n"))},
    "spc_set_id": {  # M0 defect: the _ID card comes before the main card
        "main.k": deck("boundary spc set with id",
                       BASE + "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n"
                       + "*BOUNDARY_SPC_SET_ID\n" + i10(7) + "fixed edge\n" + i10(1, 0, 1, 1, 1, 1, 1, 1) + "\n")},
    "zero_ref": {  # M0 defect: 0 in a reference field is no reference (eosid, hgid, tmid all 0)
        "main.k": deck("zero references", BASE.replace(PART, "*PART\nplate\n" + i10(1, 1, 1, 0, 0, 0, 0, 0) + "\n"))},
}

for name, files in CASES.items():
    for rel, text in files.items():
        path = HERE / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("latin-1"))
```

- [ ] **Step 2: Generate the cases and inspect two by eye**

Run: `.venv/Scripts/python tests/torture/make_m1c_cases.py && cat tests/torture/table_dangling/main.k tests/torture/spc_set_id/main.k`
Expected:
- 15 new folders.
- In `table_dangling`, the table rows are 30 columns wide (value right-aligned to column 20, id to column 30).
- In `spc_set_id`, the id card `         7fixed edge` comes before the `nsid` card.

- [ ] **Step 3: Ask LS-DYNA**

Run: `.venv/Scripts/python -m bakeoff.referee_cases table_dangling table_ids contact_type2_bad contact_type3_bad contact_type4_bad velocity_styp1_bad velocity_styp3_bad inc_path_in_include inc_blank_in_continuation inc_empty long_keyword long_section parameter_ref spc_set_id zero_ref > bakeoff/results/m1c_referee.txt`
Expected: 15 verdicts, about 3 s each. Hypotheses, none binding:
- `table_ids`, `inc_path_in_include`, `inc_empty`, `long_keyword`, `long_section`, `parameter_ref`, `spc_set_id`
  and `zero_ref` accepted;
- the five `_bad` cases and `table_dangling` rejected;
- `inc_blank_in_continuation` either way.

Read each rejection's deciding lines. A rejection for a reason other than the question (for example a card the
probe wrote wrong) is a broken probe. Fix the generator, rerun that case and note it in the ledger. A broken probe
is never recorded as an answer.

- [ ] **Step 4: Run the offset and absolute-path probes**

Create `bakeoff/m1c_probes.py`:

```python
"""Ask LS-DYNA (a) which *INCLUDE_TRANSFORM offset field applies to which entity kind, and (b) whether an absolute
include name is read. Probe decks are built in temporary folders, never committed (M1c plan, Task 1).

(a) One entity of the kind, id 1, sits in sub.k. Every offset field gets a distinct value, and the main deck
references the entity as 1 + one candidate field's offset. A control run (all offsets 0, reference 1) must pass
first. Kinds whose probe needs another kind's offset run after it."""
import json
import tempfile
from pathlib import Path

from bakeoff.lsdyna_oracle import lsdyna_reads

FIELDS = ["idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff", "iddoff", "idroff"]
DISTINCT = {f: 100 * (i + 1) for i, f in enumerate(FIELDS)}
ZERO = {f: 0 for f in FIELDS}
OUT = Path("bakeoff/results/m1c_probes.json")


def i10(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def transform(off: dict[str, int]) -> str:
    return ("*INCLUDE_TRANSFORM\nsub.k\n" + i10(*(off[f] for f in FIELDS[:7])) + "\n" + i10(off["idroff"])
            + "\n\n\n")


def nodes(first: int) -> str:
    xy = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    return "*NODE\n" + "".join(f"{first + k:>8}{x:>16}{y:>16}{0.0:>16}\n" for k, (x, y) in enumerate(xy))


def model(pid=1, sec=1, mat=1, hg=0, n0=0, part_id=1, sec_id=1, mat_id=1, skip=()) -> str:
    """A one-element model; ids that point elsewhere are parameters, and `skip` drops kinds that live in sub.k."""
    out = ""
    if "PART" not in skip:
        out += "*PART\nplate\n" + i10(part_id, sec, mat, 0, hg) + "\n"
    if "SECTION" not in skip:
        out += "*SECTION_SHELL\n" + i10(sec_id, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
    if "MAT" not in skip:
        out += "*MAT_ELASTIC\n" + i10(mat_id, "7.85E-9", "210000.0", 0.3) + "\n"
    if "NODE" not in skip:
        out += nodes(n0 + 1)
    out += "*ELEMENT_SHELL\n" + "".join(f"{v:>8}" for v in (1, pid, n0 + 1, n0 + 2, n0 + 3, n0 + 4)) + "\n"
    return out


def probe(kind: str, ref: int, known: dict[str, int]) -> tuple[str, str]:
    """(main body, sub.k body) asking whether the main deck's reference `ref` reaches the entity in sub.k."""
    if kind == "MAT":
        return model(mat=ref, skip=("MAT",)), "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n"
    if kind == "SECTION":
        return model(sec=ref, skip=("SECTION",)), "*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
    if kind == "HOURGLASS":
        return model(hg=ref), "*HOURGLASS\n" + i10(1, 1) + "\n"
    if kind == "NODE":
        return model(n0=ref - 1, skip=("NODE",)), nodes(1)
    if kind == "DEFINE_CURVE":
        return (model() + "*LOAD_NODE_POINT\n" + i10(1, 3, ref, 1.0) + "\n",
                "*DEFINE_CURVE\n" + i10(1) + "\n" + f"{0.0:>20}{1.0:>20}\n{1.0:>20}{1.0:>20}\n")
    if kind == "PART":  # sub.k's part points at section 1 and material 1, shifted by their own offsets
        return (model(pid=ref, sec_id=1 + known["SECTION"], mat_id=1 + known["MAT"], skip=("PART",)),
                "*PART\nplate\n" + i10(1, 1, 1) + "\n")
    if kind == "SET_PART":  # sub.k's set lists part 1, shifted by the part offset
        p = 1 + known["PART"]
        return (model(pid=p, part_id=p) + "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(ref, 0, 2, 0) + "\n"
                + i10(0.0, 0.0) + "\n" + i10(1.0, 1.0) + "\n", "*SET_PART_LIST\n" + i10(1) + "\n" + i10(1) + "\n")
    if kind == "SET_NODE":  # sub.k's set lists nodes 1 and 2, shifted by the node offset
        n0 = known["NODE"]
        return (model(n0=n0) + "*BOUNDARY_SPC_SET\n" + i10(ref, 0, 1, 1, 1, 1, 1, 1) + "\n",
                "*SET_NODE_LIST\n" + i10(1) + "\n" + i10(1, 2) + "\n")
    raise ValueError(kind)


NEEDS = {"PART": ("SECTION", "MAT"), "SET_PART": ("PART",), "SET_NODE": ("NODE",)}
ORDER = ["MAT", "SECTION", "HOURGLASS", "NODE", "DEFINE_CURVE", "PART", "SET_PART", "SET_NODE"]


def run(main_body: str, sub: str, off: dict[str, int]) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp)
        head = "*KEYWORD\n*TITLE\ndeckcheck offset probe\n*CONTROL_TERMINATION\n    1.0E-6\n"
        (case / "main.k").write_bytes((head + transform(off) + main_body + "*END\n").encode("latin-1"))
        (case / "sub.k").write_bytes(("*KEYWORD\n" + sub + "*END\n").encode("latin-1"))
        return lsdyna_reads(case)[0]


def offsets() -> dict:
    out, known = {}, {}
    for kind in ORDER:
        if any(k not in known for k in NEEDS.get(kind, ())):
            out[kind] = {"control": None, "accepted": [], "decided": None, "skipped": "a needed kind is undecided"}
            continue
        # the control shifts nothing, so a needed kind's offset is 0 there too
        control = run(*probe(kind, 1, {k: 0 for k in known}), ZERO)
        shifted = {k: DISTINCT[f] for k, f in known.items()}
        accepted = [f for f in FIELDS if control and run(*probe(kind, 1 + DISTINCT[f], shifted), DISTINCT)]
        decided = accepted[0] if control and len(accepted) == 1 else None
        if decided:
            known[kind] = decided
        out[kind] = {"control": control, "accepted": accepted, "decided": decided}
        print(kind, out[kind], flush=True)
    return out


def absolute_include() -> bool:
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as lib:
        mat = Path(lib) / "mat.k"
        mat.write_bytes(("*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n").encode("latin-1"))
        head = "*KEYWORD\n*TITLE\ndeckcheck absolute include\n*CONTROL_TERMINATION\n    1.0E-6\n"
        (Path(tmp) / "main.k").write_bytes((head + f"*INCLUDE\n{mat}\n" + model(skip=("MAT",)) + "*END\n")
                                           .encode("latin-1"))
        return lsdyna_reads(Path(tmp))[0]


if __name__ == "__main__":
    OUT.write_text(json.dumps({"offsets": offsets(), "inc_absolute": absolute_include()}, indent=1), encoding="utf-8")
```

`model()` in the PART probe defines the element's part as `pid=ref`. The part itself lives in `sub.k` with id 1, so
the element's part is found only if `ref` is the shifted id.

Note: `lsdyna_reads` copies the case folder into its own temp folder. The absolute path in `absolute_include` points
outside both folders, so the copy does not matter.

Run: `.venv/Scripts/python -m bakeoff.m1c_probes`
Expected:
- about 75 LS-DYNA runs, about 4 minutes;
- a printed line per kind, each with `control: True` and one accepted field (hypothesis only: MAT idmoff, NODE
  idnoff, PART idpoff, SET_* idsoff, DEFINE_CURVE idfoff);
- `inc_absolute` true or false.

Read the file. A kind with `control: False` has a broken probe: fix it and rerun. A kind with zero or several
accepted fields stays undecided (`decided: null`). That is a legitimate answer, and Task 6 then treats the kind as
uncertain under any nonzero transform.

- [ ] **Step 5: Record the verdicts**

For each of the 15 cases, write `expected.toml` with `lsdyna_valid` set to LS-DYNA's verdict, `findings = []` and a
`note` in the M1b form: `"Q: <question>. LS-DYNA R16.1 Student 2026-10-29: <accepted|rejected>, <deciding line>."`.
For each rejected case, add an `[index]` table that locates by hand what LS-DYNA complained about. For example,
for `table_dangling` (the row `0.0  99` is line 18, and the id field is columns 20–30, with `99` at 28–30):

```toml
[index]
dangling = [{kind = "DEFINE_CURVE", id = 99, file = "main.k", line = 18, columns = [28, 30]}]
```

Compute each line and span from the generated file (`grep -n`), not from this example. If a `_bad` case was
**accepted**, LS-DYNA does not check that reference. Record that as a ruling, and in Task 6 remove the matching
`map` entry from `overrides.toml` (an unchecked reference must not become a deckcheck error).

Add the 15 names to `CASES` in `tests/test_torture_layout.py`.

- [ ] **Step 6: Run the layout test**

Run: `.venv/Scripts/python -m pytest tests/test_torture_layout.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/torture bakeoff/m1c_probes.py bakeoff/results/m1c_referee.txt bakeoff/results/m1c_probes.json tests/test_torture_layout.py
git commit -m "M1c Task 1: LS-DYNA decides the field reading rules (15 cases, offset probes)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Extraction v2 — conditions, lengths, defaults

**Files:**
- Modify: `tools/extract_keyword_data.py`, `tests/test_extract.py`, `src/deckcheck/data/keywords.json`
  (regenerated)

**Interfaces:**
- Produces, in `keywords.json`:
  - every card dict has `when: str | None`, the condition as Python source with `self.` names, or `None`;
  - every `table`, `series`, `card_set` and `table_group` has `length: str | None`, where `None` is unbounded (read
    to the end of the block);
  - every field dict has `default: int | float | str | None`.

  `"?"` marks a lambda whose source could not be pinned to one expression. `conditional` stays (true when `when`
  is set).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_extract.py`:

```python
def _walk(cards):
    for c in cards:
        yield c
        yield from _walk(c.get("cards", []))


def test_section_shell_conditions_and_lengths(data):
    item = data["keywords"]["SECTION_SHELL"]["cards"][0]
    assert item["kind"] == "card_set" and item["length"] is None
    angle = [c for c in item["cards"] if c.get("name") == "angle"][0]
    assert angle["when"] == "self.icomp == 1"
    assert angle["length"] == "2 if self.nip == 0 else self.nip"
    xi = [c for c in item["cards"] if c["kind"] == "table"][0]
    assert xi["length"] == "self.nipp"
    assert xi["when"] == "self.elform in [101, 102, 103, 104, 105]"


def test_unbounded_tables_have_no_length(data):
    curve = [c for c in data["keywords"]["DEFINE_CURVE"]["cards"] if c["kind"] == "table"][0]
    assert curve["length"] is None and curve["when"] is None


def test_field_defaults(data):
    first = data["keywords"]["SECTION_SHELL"]["cards"][0]["cards"][0]["fields"]
    assert {f["name"]: f["default"] for f in first}["nip"] == 2
    assert {f["name"]: f["default"] for f in first}["icomp"] == 0
    assert {f["name"]: f["default"] for f in first}["secid"] is None


def test_every_card_has_when_and_counts_have_length(data):
    for k in data["keywords"].values():
        for c in _walk(k["cards"]):
            assert "when" in c and c["conditional"] == (c["when"] is not None)
            if c["kind"] in ("table", "series", "card_set", "table_group"):
                assert "length" in c
```

Change the last assertion of `test_spc_set_id_option_and_links`, because fields now carry `default`:

```python
    assert {k: v for k, v in main["fields"][0].items() if k != "default"} == {
        "name": "nsid", "type": "int", "offset": 0, "width": 10}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv-extract/Scripts/python -m pytest tests/test_extract.py -q -m extract`
Expected: the 4 new tests FAIL with `KeyError: 'length'` / `'default'` / `'when'`; the others pass.

- [ ] **Step 3: Extract conditions, lengths and defaults**

In `tools/extract_keyword_data.py`, add `import ast` and `import functools` to the imports, and add after the
imports:

```python
CORE = Path(kw.__file__).parent.parent  # ansys/dyna/core
LIB = CORE / "lib"


@functools.cache
def _lambdas(path: str) -> dict[int, list[ast.Lambda]]:
    out: dict[int, list[ast.Lambda]] = {}
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Lambda):
            out.setdefault(node.lineno, []).append(node)
    return out


def _source(fn) -> str | None:
    """A card's condition or length lambda as Python source. None: no function, or pydyna's library default
    (a table or series read to the end of the block). "?": the lambda could not be pinned to one expression."""
    if fn is None:
        return None
    path = Path(fn.__code__.co_filename)
    if path.is_relative_to(LIB):
        return None
    texts = {ast.unparse(n.body) for n in _lambdas(str(path)).get(fn.__code__.co_firstlineno, [])}
    return texts.pop() if len(texts) == 1 else "?"


def _default(value):
    return value if type(value) in (int, float, str) else None
```

In `_fields`, add the default to each field dict:

```python
            out.append({"name": item.name, "type": getattr(item.type, "__name__", str(item.type)),
                        "offset": item.offset, "width": item.width, "default": _default(item.default)})
```

In `_card`, replace the `base` line and the four repeated kinds:

```python
    when = _source(getattr(card, "_active_func", None))
    base = {"option": option, "conditional": when is not None, "when": when}
    length = {"length": _source(getattr(card, "_length_func", None))}
```

```python
    if kind == "TableCard":
        return {"kind": "table", **base, **length, "fields": _fields(card._schema)}
    if kind == "TableCardGroup":
        rows = {"length": _source(getattr(card._cards[0], "_length_func", None))}
        return {"kind": "table_group", **base, **rows,
                "cards": [c for sub in card._cards for c in _flat(_card(sub, option))]}
    if kind == "SeriesCard":
        return {"kind": "series", **base, **length, "name": card._name, "element_width": card._element_width,
                "per_card": card._fields_per_card, "type": getattr(card._type, "__name__", str(card._type))}
    if kind == "CardSet":
        item = card._items[0] if card._items else card._set_type(parent=card, keyword=card._keyword)
        return {"kind": "card_set", **base, **length,
                "cards": [c for sub in item._cards for c in _flat(_card(sub, option))]}
```

- [ ] **Step 4: Run the tests**

Run: `.venv-extract/Scripts/python -m pytest tests/test_extract.py -q -m extract`
Expected: all PASS.

If `test_section_shell_conditions_and_lengths` fails only on a sub-card's `when` inside a `table_group` or
`card_set`, the condition is stored under another attribute name. Find it with
`vars(card)` in the extract venv, use it, and ledger a ruling.

- [ ] **Step 5: Regenerate the data and check the tally**

Run: `.venv-extract/Scripts/python tools/extract_keyword_data.py src/deckcheck/data/keywords.json && .venv/Scripts/python -c "import json,collections; d=json.load(open('src/deckcheck/data/keywords.json',encoding='utf-8'))['keywords']; w=lambda cs:[x for c in cs for x in [c]+w(c.get('cards',[]))]; c=collections.Counter((k in x and x[k] is not None, x.get(k)=='?') for v in d.values() for x in w(v['cards']) for k in ('when','length')); print(c)"`
Expected:
- about 275 conditions and about 140 bounded lengths, with zero or very few `"?"` (the scoping prototype found
  none);
- the file grows by well under 1 MB.

Record the counts for the report.

- [ ] **Step 6: Run the runtime suite on the new data**

Run: `.venv/Scripts/python -m pytest -q -m "not extract and not lsdyna and not corpus"`
Expected: PASS, the same count as before plus the new layout cases. M1b code reads `fields` by name, so the extra
keys don't touch it.

- [ ] **Step 7: Commit**

```bash
git add tools/extract_keyword_data.py tests/test_extract.py src/deckcheck/data/keywords.json
git commit -m "M1c Task 2: extract card conditions, lengths and field defaults

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The condition evaluator

**Files:**
- Create: `src/deckcheck/conditions.py`, `tests/test_conditions.py`

**Interfaces:**
- Produces:
  - `UNKNOWN` (sentinel);
  - `Scope(parent=None)` with `.values: dict[str, object]` and `.parent`;
  - `compile_expr(text: str) -> ast.Expression | None`, where `None` means outside the grammar;
  - `evaluate(tree, scope) -> object`, which returns `UNKNOWN` when undecidable;
  - `names_in(text: str) -> frozenset[str]` (field names an expression reads).

  `self.x` reads `scope.values["x"]`. `self.parent.x` reads `scope.parent.values["x"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_conditions.py`:

```python
import pytest

from deckcheck.conditions import UNKNOWN, Scope, compile_expr, evaluate, names_in
from deckcheck.keywords import load


def run(text, parent=None, **values):
    scope = Scope(parent)
    scope.values.update(values)
    return evaluate(compile_expr(text), scope)


def test_section_shell_forms():
    assert run("self.icomp == 1", icomp=1) is True
    assert run("2 if self.nip == 0 else self.nip", nip=0) == 2
    assert run("2 if self.nip == 0 else self.nip", nip=5) == 5
    assert run("self.elform in [101, 102, 103, 104, 105]", elform=2) is False


def test_parent_and_functions():
    parent = Scope()
    parent.values["nhisv"] = 3
    assert run("self.parent.nhisv", parent) == 3
    assert run("math.ceil((self.nr + self.pr + 1) / 4)", nr=4, pr=2) == 2
    assert run("abs(self.dof) in [9, 10, 11] or self.vad == 4", dof=-10, vad=0) is True


def test_unknown_propagates_but_short_circuits():
    assert run("self.missing == 1") is UNKNOWN
    assert run("self.a > 0 and self.missing", a=0) is False
    assert run("self.a > 0 or self.missing", a=1) is True
    assert run("self.a > 0 and self.missing", a=1) is UNKNOWN
    assert run("self.a > 0", a=None) is UNKNOWN  # None > 0 is a TypeError: undecided, not False


def test_outside_the_grammar_is_refused():
    for text in ["self._cards[1].has_nondefault_values()", "__import__('os')", "self.elements['n5'].any()",
                 "(lambda: 1)()", "self.a.b.c", "?"]:
        assert compile_expr(text) is None, text


def test_names_in():
    assert names_in("2 if self.nip == 0 else self.nip") == {"nip"}
    assert names_in("self.parent.large == 1") == {"large"}


def test_extracted_expressions_compile_or_are_known_exceptions():
    def walk(cards):
        for c in cards:
            yield c
            yield from walk(c.get("cards", []))
    refused = {t for k in load()["keywords"].values() for c in walk(k["cards"])
               for t in (c.get("when"), c.get("length")) if t and compile_expr(t) is None}
    # every refused text reads another card's state or a pandas frame: undecidable from field values
    assert all(any(m in t for m in ("_cards[", ".any()", ".empty", "has_nondefault", ".iloc", "?")) for t in refused), refused
    assert len(refused) <= 30
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_conditions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.conditions'`.

- [ ] **Step 3: Write the evaluator**

Create `src/deckcheck/conditions.py`:

```python
"""Evaluate pydyna's card conditions and lengths (extracted as source text by tools/extract_keyword_data.py)
without running code: a small evaluator over a whitelisted subset of Python expressions. Undecidable -> UNKNOWN."""
import ast
import functools
import math


class _Unknown:
    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN = _Unknown()

FUNCS = {("abs",): abs, ("int",): int, ("max",): max, ("min",): min, ("math", "ceil"): math.ceil}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}
_CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
        ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b}


class Scope:
    def __init__(self, parent: "Scope | None" = None):
        self.values: dict[str, object] = {}
        self.parent = parent


def _chain(node) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        inner = _chain(node.value)
        return inner + (node.attr,) if inner else None
    return None


def _is_field(chain) -> bool:
    return chain is not None and (len(chain) == 2 and chain[0] == "self"
                                  or len(chain) == 3 and chain[:2] == ("self", "parent"))


def _allowed(n) -> bool:
    if isinstance(n, ast.Constant):
        return True
    if isinstance(n, (ast.List, ast.Tuple)):
        return all(map(_allowed, n.elts))
    if isinstance(n, (ast.Attribute, ast.Name)):
        return _is_field(_chain(n))
    if isinstance(n, ast.BoolOp):
        return all(map(_allowed, n.values))
    if isinstance(n, ast.UnaryOp):
        return isinstance(n.op, (ast.Not, ast.USub, ast.UAdd)) and _allowed(n.operand)
    if isinstance(n, ast.BinOp):
        return type(n.op) in _BIN and _allowed(n.left) and _allowed(n.right)
    if isinstance(n, ast.Compare):
        return all(type(op) in _CMP for op in n.ops) and _allowed(n.left) and all(map(_allowed, n.comparators))
    if isinstance(n, ast.IfExp):
        return _allowed(n.test) and _allowed(n.body) and _allowed(n.orelse)
    if isinstance(n, ast.Call):
        return _chain(n.func) in FUNCS and not n.keywords and all(map(_allowed, n.args))
    return False


@functools.cache
def compile_expr(text: str) -> ast.Expression | None:
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    return tree if _allowed(tree.body) else None


def names_in(text: str) -> frozenset[str]:
    tree = compile_expr(text)
    if tree is None:
        return frozenset()
    return frozenset(c[-1] for n in ast.walk(tree) if _is_field(c := _chain(n)))


def evaluate(tree: ast.Expression, scope: Scope) -> object:
    try:
        return _eval(tree.body, scope)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return UNKNOWN


def _eval(n, s: Scope) -> object:
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, (ast.List, ast.Tuple)):
        items = [_eval(e, s) for e in n.elts]
        return UNKNOWN if any(i is UNKNOWN for i in items) else items
    if isinstance(n, (ast.Attribute, ast.Name)):
        chain = _chain(n)
        scope = s if len(chain) == 2 else s.parent
        return UNKNOWN if scope is None else scope.values.get(chain[-1], UNKNOWN)
    if isinstance(n, ast.BoolOp):
        result, unknown = None, False
        for v in n.values:
            r = _eval(v, s)
            if r is UNKNOWN:
                unknown = True
            elif isinstance(n.op, ast.And) and not r:
                return r
            elif isinstance(n.op, ast.Or) and r:
                return r
            else:
                result = r
        return UNKNOWN if unknown else result
    if isinstance(n, ast.UnaryOp):
        v = _eval(n.operand, s)
        if v is UNKNOWN:
            return UNKNOWN
        return not v if isinstance(n.op, ast.Not) else -v if isinstance(n.op, ast.USub) else +v
    if isinstance(n, ast.BinOp):
        a, b = _eval(n.left, s), _eval(n.right, s)
        return UNKNOWN if a is UNKNOWN or b is UNKNOWN else _BIN[type(n.op)](a, b)
    if isinstance(n, ast.Compare):
        left = _eval(n.left, s)
        for op, comp in zip(n.ops, n.comparators):
            right = _eval(comp, s)
            if left is UNKNOWN or right is UNKNOWN:
                return UNKNOWN
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(n, ast.IfExp):
        t = _eval(n.test, s)
        return UNKNOWN if t is UNKNOWN else _eval(n.body if t else n.orelse, s)
    args = [_eval(a, s) for a in n.args]  # ast.Call: _allowed admitted only FUNCS
    return UNKNOWN if any(a is UNKNOWN for a in args) else FUNCS[_chain(n.func)](*args)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_conditions.py -q`
Expected: 6 PASS.

If `test_extracted_expressions_compile_or_are_known_exceptions` lists a refused text that reads only field values,
widen the grammar with a matching test case. If it reads card state, add its marker to the list and ledger a
ruling. Such cards make the field reader stop (`unread`), which is safe.

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck/conditions.py tests/test_conditions.py
git commit -m "M1c Task 3: whitelisted evaluator for card conditions and lengths

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The field reader

**Files:**
- Modify: `src/deckcheck/keywords.py` (add `walk_cards`, `layout`), `src/deckcheck/fields.py` (field reader),
  `src/deckcheck/data/overrides.toml` (Task 1 rulings on `map` entries, if any)
- Create: `tests/test_fields.py`

**Interfaces:**
- Consumes: `conditions.*` (Task 3); `when`/`length`/`default` in the data (Task 2); `reader.Block`, `reader.Card`;
  Task 1's verdicts on `long_keyword` and `long_section`.
- Produces:
  - `keywords.walk_cards(cards) -> Iterator[dict]`.
  - `keywords.layout(key) -> dict`: the data entry with overrides applied. Fields and series may carry `link`,
    `link_by`, `link_map` and `link_when`; the `options` list includes added options.
  - `fields.Field(name, line, start, end, value, group, spec)` and `fields.FieldProblem(kind, line, start, end,
    detail)`, where kind is `unread`, `extra` or `bad`.
  - `fields.read_fields(block, params=None, long_deck=False, wanted=None, problems=None) -> Iterator[Field]`.
  - `fields.LONG_KEYWORD` (bool, from `long_keyword`).

  `Value`, `card_values` and `_value` are unchanged (used by `includes.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fields.py`:

```python
from deckcheck.conditions import UNKNOWN
from deckcheck.fields import read_fields
from deckcheck.keywords import layout
from deckcheck.reader import read_file


def block(tmp_path, text):
    path = tmp_path / "b.k"
    path.write_bytes(text.encode("latin-1"))
    return read_file(path).blocks[0]


def fields(tmp_path, text, **kw):
    problems = []
    out = list(read_fields(block(tmp_path, text), problems=problems, **kw))
    return out, problems


def values(out, name):
    return [f.value for f in out if f.name == name]


def test_section_shell_card_set_with_conditional_series(tmp_path):
    out, problems = fields(tmp_path, "*SECTION_SHELL\n"
                           "         1         2       1.0         3       0.0         0         1\n"
                           "       1.0       1.0       1.0       1.0\n"
                           "       0.0      45.0      90.0\n"
                           "         2         2\n"
                           "       2.0       2.0       2.0       2.0\n")
    assert values(out, "secid") == [1, 2]
    assert values(out, "angle") == [0.0, 45.0, 90.0]
    assert [f.line for f in out if f.name == "angle"] == [4, 4, 4]
    assert values(out, "t1") == [1.0, 2.0]
    assert problems == []


def test_part_table_group_with_blank_heading(tmp_path):
    out, problems = fields(tmp_path, "*PART\n\n         1         1         1\nsecond\n         2         1         1\n")
    pids = [f for f in out if f.name == "pid"]
    assert [(f.value, f.line, f.start, f.end) for f in pids] == [(1, 3, 9, 10), (2, 5, 9, 10)]
    assert problems == []


def test_id_option_card_comes_first(tmp_path):
    out, _ = fields(tmp_path, "*BOUNDARY_SPC_SET_ID\n         7fixed end\n         3         0         1\n")
    assert values(out, "id") == [7] and values(out, "nsid") == [3]
    assert [f.line for f in out if f.name == "nsid"] == [3]


def test_long_format_suffix(tmp_path):
    line = f"{1:>20}{'7.85E-9':>20}{'210000.0':>20}{0.3:>20}"
    out, _ = fields(tmp_path, "*MAT_ELASTIC +\n" + line + "\n")
    mid = [f for f in out if f.name == "mid"][0]
    assert (mid.value, mid.start, mid.end) == (1, 19, 20)
    assert values(out, "e") == [210000.0]


def test_free_format(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n1,7.85E-9,210000.0,0.3\n")
    mid = [f for f in out if f.name == "mid"][0]
    assert (mid.value, mid.start, mid.end) == (1, 0, 1)
    assert values(out, "pr") == [0.3]


def test_free_card_short(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n1,2\n")
    assert values(out, "mid") == [1] and values(out, "e") == [None]
    assert [f for f in out if f.name == "ro"][0][2:4] == (2, 3)
    assert problems == []


def test_full_width_value(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n1234567890   7.85E-9\n")
    mid = [f for f in out if f.name == "mid"][0]
    assert (mid.value, mid.start, mid.end) == (1234567890, 0, 10)


def test_blank_row_in_table(tmp_path):
    out, problems = fields(tmp_path, "*NODE\n       1             0.0\n\n       2             1.0\n")
    nids = [(f.value, f.line) for f in out if f.name == "nid"]
    assert nids == [(1, 2), (None, 3), (2, 4)]
    assert problems == []


def test_parameter_substitution(tmp_path):
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9    &young       0.3\n",
                    params={"YOUNG": 210000.0})
    assert values(out, "e") == [210000.0]
    out, _ = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9     &nope       0.3\n", params={})
    assert values(out, "e") == [UNKNOWN]


def test_undecided_condition_stops_the_block(tmp_path):
    out, problems = fields(tmp_path, "*SECTION_SHELL\n"
                           "         1         2       1.0         3       0.0         0    &undef\n"
                           "       1.0       1.0       1.0       1.0\n"
                           "       0.0      45.0      90.0\n", params={})
    assert values(out, "secid") == [1]
    assert [(p.kind, p.line) for p in problems] == [("unread", 4)]


def test_extra_cards_are_reported(tmp_path):
    _, problems = fields(tmp_path, "*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n       9.9\n")
    assert [(p.kind, p.line) for p in problems] == [("extra", 3)]


def test_bad_value(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n       abc   7.85E-9\n")
    assert values(out, "mid") == [UNKNOWN]
    assert [(p.kind, p.line, p.start, p.end) for p in problems] == [("bad", 2, 7, 10)]


def test_integral_float_in_int_field(tmp_path):
    out, problems = fields(tmp_path, "*MAT_ELASTIC\n        1.\n")
    assert values(out, "mid") == [1] and problems == []


def test_contact_optional_card_a_is_not_extra(tmp_path):
    _, problems = fields(tmp_path, "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n         1         0         2\n"
                         "       0.0\n       1.0\n         1\n")
    assert problems == []


def test_wanted_filters_fields(tmp_path):
    out, _ = fields(tmp_path, "*PART\nplate\n         1         2         3\n", wanted=frozenset({"mid"}))
    assert [(f.name, f.value) for f in out] == [("mid", 3)]


def test_layout_applies_overrides():
    table = layout("DEFINE_TABLE")["cards"]
    rows = [c for c in table if c["kind"] == "table"][0]
    assert [(f["name"], f["width"], f.get("link")) for f in rows["fields"]] == [
        ("value", 20, None), ("lcid", 10, "DEFINE_CURVE")]
    surfa = [f for c in layout("CONTACT_AUTOMATIC_GENERAL")["cards"] for f in c.get("fields", []) if f["name"] == "surfa"][0]
    assert surfa["link_by"] == "surfatyp" and surfa["link_map"]["2"] == "SET_PART"
    assert layout("PART")["cards"][0]["cards"][1]["fields"][2]["link"] == "MAT"
    assert "ID" in {o["name"] for o in layout("CONSTRAINED_JOINT_REVOLUTE")["options"]}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_fields.py -q`
Expected: FAIL at import: `cannot import name 'read_fields'` / `'layout'`.

- [ ] **Step 3: Add `walk_cards` and `layout` to `keywords.py`**

Add `import copy` to the imports, and append to `src/deckcheck/keywords.py`:

```python
def walk_cards(cards: list[dict]):
    for c in cards:
        yield c
        yield from walk_cards(c.get("cards", []))


@functools.cache
def _targets() -> list[tuple[dict, frozenset[str]]]:
    return [(o, frozenset(override_targets(o))) for o in overrides()["override"]]


def _link_facts(s: dict) -> dict:
    facts = {"link": s.get("link"), "link_by": s.get("link_by"), "link_map": s.get("map"), "link_when": s.get("when")}
    return {k: v for k, v in facts.items() if v is not None}


@functools.cache
def layout(key: str) -> dict:
    """The keyword's data entry with every override applied: per-field link facts (link, link_by + link_map,
    link_when), replaced series layouts and added option cards. Read-only: callers share the cached dict."""
    entry = copy.deepcopy(load()["keywords"][key])
    links = entry["links"]
    for card in walk_cards(entry["cards"]):
        if card["kind"] == "series" and card["name"] in links:
            card["link"] = links[card["name"]]
        for f in card.get("fields", []):
            if f["name"] in links:
                f["link"] = links[f["name"]]
    for o, keys in _targets():
        if key not in keys:
            continue
        s = o["set"]
        if "defines" in s:
            continue  # definitions are deckcheck.definers' business
        if "add_option" in s:
            opt = s["add_option"]
            entry["options"].append({"name": opt["name"], "position": opt["position"], "title_order": 0})
            entry["cards"].append({"kind": "card", "option": opt["name"], "conditional": False, "when": None,
                                   "fields": [dict(f, default=None) for f in opt["fields"]]})
            continue
        if "replace_with" in s:
            entry["cards"] = [
                {"kind": "table", "option": c["option"], "conditional": False, "when": None, "length": None,
                 "fields": [dict(f, default=None) for f in s["replace_with"]]}
                if c.get("name") == o["card"] else c for c in entry["cards"]]
            continue
        names = {o["field"]} if "field" in o else set(o.get("fields", []))
        for card in walk_cards(entry["cards"]):
            if card["kind"] == "series" and card.get("name") == o.get("card"):
                card.update(_link_facts(s))
            for f in card.get("fields", []):
                if f["name"] in names:
                    f.update(_link_facts(s))
    return entry
```

- [ ] **Step 4: Write the field reader**

Replace the module docstring of `src/deckcheck/fields.py`, and add after `card_values`:

```python
"""Field values of a keyword block, by the keyword data's layout (deckcheck.keywords.layout): option-card
placement, tables, series and card sets, conditional cards (deckcheck.conditions), long and free format, and
*PARAMETER substitution (spec §4, field reader row). Where it can't decide, it stops and says so (`unread`)."""
import functools
import itertools
from typing import Iterator, NamedTuple

from deckcheck.conditions import UNKNOWN, Scope, compile_expr, evaluate, names_in
from deckcheck.keywords import layout, walk_cards
from deckcheck.reader import Block, Card

LONG_KEYWORD = True  # long_keyword: *KEYWORD LONG=S makes every card long (set from Task 1's verdict)
LONG_WIDTH = 20      # pydyna's to_long: each field max(width, 20), one line per card (long_section)
OPTIONAL_TRAILING = frozenset("ABCDEFG")  # contact optional cards A-G: read when present (pydyna: post options)
```

(keep the `Value`, `_value` and `card_values` definitions between the docstring/imports and the code below)

```python
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

    def container(self, cards: list[dict], scope: Scope, top: bool) -> Iterator[Field]:
        for spec in _ordered(cards, self.key, self.options, top):
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
    yield from reader.container(layout(block.resolved.name)["cards"], Scope(), True)
    if not reader.stopped:
        rest = [c for c in block.cards[reader.i:] if c.text.strip()]
        if rest:
            problems.append(FieldProblem("extra", rest[0].line, 0, len(rest[0].text.rstrip()),
                                         f"{len(rest)} card(s) past the layout"))
```

Set `LONG_KEYWORD` from Task 1's `long_keyword` verdict. If `long_section` was **rejected**, LS-DYNA does not keep
an 8-field long card on one line. Then make `card()` stop with `self.stop("long-format card wider than 80 columns")`
when `self.long` and the card's fields total more than 80 columns, and ledger the ruling.

If Task 1 found a `_bad` case **accepted**, delete that `map` entry from `overrides.toml` now, with the case named in
the entry's `evidence`.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_fields.py -q`
Expected: 17 PASS.

Where a test fails because the data's layout differs from the test's assumption, check the layout first with
`layout(key)`. Two cases:
- The data says what LS-DYNA reads: fix the test's deck text, and ledger it.
- The data is wrong for an LS-DYNA-accepted deck: add an override with evidence.

For example, `test_contact_optional_card_a_is_not_extra` assumes the contact has three main cards.

- [ ] **Step 6: Run the whole fast suite**

Run: `.venv/Scripts/python -m pytest -q -m "not extract and not lsdyna and not corpus"`
Expected: PASS (M1b's include tests still use `card_values`).

- [ ] **Step 7: Commit**

```bash
git add src/deckcheck/keywords.py src/deckcheck/fields.py src/deckcheck/data/overrides.toml tests/test_fields.py
git commit -m "M1c Task 4: field reader (options, tables, series, card sets, conditions, long/free format)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: *PARAMETER values

**Files:**
- Create: `src/deckcheck/params.py`, `tests/test_params.py`

**Interfaces:**
- Consumes: `includes.Tree`; `conditions.UNKNOWN`.
- Produces: `params.collect(tree) -> dict[str, object]`, mapping upper-case names to an int, float or str, or
  `UNKNOWN`. The field reader's `params` argument takes this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_params.py`:

```python
from pathlib import Path

from deckcheck.conditions import UNKNOWN
from deckcheck.includes import resolve_tree
from deckcheck.params import collect

TORTURE = Path(__file__).parent / "torture"


def tree(tmp_path, text):
    (tmp_path / "main.k").write_bytes(text.encode("latin-1"))
    return resolve_tree(tmp_path / "main.k")


def test_torture_parameter():
    assert collect(resolve_tree(TORTURE / "parameter" / "main.k")) == {"YOUNG": 210000.0}


def test_types_pairs_and_free_format(tmp_path):
    t = tree(tmp_path, "*KEYWORD\n*PARAMETER\nI mm               1R rho        7.85E-9\nC name,steel\n*END\n")
    assert collect(t) == {"MM": 1, "RHO": 7.85e-9, "NAME": "steel"}


def test_what_cannot_be_known_is_unknown(tmp_path):
    t = tree(tmp_path, "*KEYWORD\n*PARAMETER\nR a              1.0\n*PARAMETER\nR a              2.0\n"
                       "*PARAMETER_EXPRESSION\nR b       a*2\nR c       3.5\n*PARAMETER_LOCAL\nI d                4\n*END\n")
    p = collect(t)
    assert p["A"] is UNKNOWN          # redefined with another value
    assert p["B"] is UNKNOWN          # an expression
    assert p["C"] == 3.5              # an expression that is a plain number
    assert p["D"] is UNKNOWN          # a scoped parameter
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_params.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.params'`.

- [ ] **Step 3: Write `params.py`**

```python
"""*PARAMETER values for field substitution (spec §4, field reader row). A name whose value deckcheck can't know
for sure (an expression, a scoped parameter, a redefinition) maps to UNKNOWN, so nothing is checked against a guess."""
from deckcheck.conditions import UNKNOWN
from deckcheck.includes import Tree
from deckcheck.reader import Card

TYPES = {"R": float, "I": int, "C": str}


def _pairs(card: Card) -> list[tuple[str, str]]:
    if card.free:
        parts = [p.strip() for p in card.text.split(",")]
    else:
        parts = [card.text[k:k + 10].strip() for k in range(0, 80, 10)]
    return [(parts[k], parts[k + 1] if k + 1 < len(parts) else "") for k in range(0, len(parts), 2) if parts[k]]


def _typed(prmr: str, text: str) -> tuple[str, object]:
    kind, name = prmr[0].upper(), prmr[1:].strip().upper()
    try:
        return name, TYPES[kind](text)
    except (KeyError, ValueError):
        return name, UNKNOWN


def collect(tree: Tree) -> dict[str, object]:
    out: dict[str, object] = {}

    def put(name: str, value: object) -> None:
        old = out.get(name, value)
        out[name] = value if old is value or old == value else UNKNOWN

    for node in tree.files:
        for block in node.source.blocks:
            if block.name == "PARAMETER":
                for card in block.cards:
                    for prmr, text in _pairs(card):
                        put(*_typed(prmr, text))
            elif block.name == "PARAMETER_EXPRESSION":
                for card in block.cards:
                    prmr, _, expr = card.text.partition(",") if card.free else (card.text[:10], "", card.text[10:])
                    if prmr.strip():
                        put(*_typed(prmr.strip(), expr.strip()))
            elif block.name.startswith("PARAMETER"):
                for card in block.cards:
                    for prmr, _ in _pairs(card):
                        put(prmr[1:].strip().upper(), UNKNOWN)
    return out
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_params.py -q`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/deckcheck/params.py tests/test_params.py
git commit -m "M1c Task 5: *PARAMETER values, UNKNOWN where deckcheck can't be sure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Definer table and the index

**Files:**
- Create: `src/deckcheck/data/definers.toml`, `src/deckcheck/definers.py`, `src/deckcheck/index.py`,
  `tests/test_definers.py`, `tests/test_index.py`
- Modify: the `expected.toml` of `seeded_mistakes`, `crlf_seeded` and `latin1_seeded` (add `[index]`)

**Interfaces:**
- Consumes:
  - `read_fields`, `Field`, `FieldProblem`, `LONG_KEYWORD` (Task 4);
  - `params.collect` (Task 5);
  - `keywords.layout`, `walk_cards`, `override_targets`, `overrides`;
  - `includes.resolve_tree`, `Tree`;
  - Task 1's `m1c_probes.json` (`decided` per kind) and each case's `[index]` table.
- Produces:
  - `definers.definers() -> dict[str, tuple[tuple[str, str], ...]]` (key → (kind, id field) pairs);
  - `definers.family_kind(name) -> str | None`;
  - `definers.not_definer(name) -> bool`;
  - `index.build(tree) -> Index`.

  `Index` holds:
  - methods: `.dangling() -> list[Ref]`, `.duplicates() -> list[Dup]`, `.used(kind) -> set[int]`,
    `.checked(kind) -> bool`;
  - attributes: `.blind: set[str]`, `.uncertain_defs` and `.uncertain_uses: dict[str, set[str]]`,
    `.problems: list[tuple[int, FieldProblem]]`, `.defs: dict[str, dict[int, int]]`.

  The record types are `Ref(kind, id, path, line, start, end, field)` and
  `Dup(kind, id, path, line, start, end, first_path, first_line)`. M1d's rules consume these.

- [ ] **Step 1: Write the definer table**

Create `src/deckcheck/data/definers.toml`:

```toml
# Which keywords define an entity of which kind, and through which id field. pydyna marks only the referring side
# (docs/m1a-keyword-data.md §4.1). A row applies to the keywords it names that have its field; each row is checked by
# tests/test_definers.py and by the M1c corpus run (docs/m1c-field-reader-index.md).
#
# [[definer]]: kind, keyword | keywords | keyword_prefix (+ exclude_prefix), field, evidence
# [[family]]:  kind, prefix. A keyword named prefix or prefix_* that no definer row covers and that is not listed in
#              not_definers makes the kind uncertain in a deck that uses it: references into the kind go unchecked.
# not_definers: keyword names (or name prefixes ending in "_") in a family that refer to the kind but define none.
# ICFD_PART definitions come from overrides.toml (set.defines).

not_definers = ["MAT_ADD_", "MAT_THERMAL_", "MAT_NONLOCAL"]

[[definer]]
kind = "NODE"
keyword = "NODE"
field = "nid"
evidence = "torture base; M0 tier-1 runs (every element node defined by *NODE)"

[[definer]]
kind = "PART"
keywords = ["PART", "PART_INERTIA", "PART_CONTACT", "PART_COMPOSITE"]
field = "pid"
evidence = "torture base, part_inertia (LS-DYNA accepted part 1 defined only by *PART_INERTIA)"

[[definer]]
kind = "MAT"
keyword_prefix = "MAT_"
exclude_prefix = ["MAT_ADD_", "MAT_THERMAL_", "MAT_NONLOCAL", "MAT_T0", "MAT_T1"]
field = "mid"
evidence = "torture base (MAT_ELASTIC), table_ids (MAT_PIECEWISE_LINEAR_PLASTICITY); MAT_ADD_* refer to a material; MAT_THERMAL_*/MAT_Tnn are the thermal namespace"

[[definer]]
kind = "SECTION"
keyword_prefix = "SECTION_"
field = "secid"
evidence = "torture base (SECTION_SHELL)"

[[definer]]
kind = "HOURGLASS"
keyword = "HOURGLASS"
field = "hgid"
evidence = "M1c offset probe HOURGLASS control (LS-DYNA accepted part hgid 1 = *HOURGLASS 1)"

[[definer]]
kind = "DEFINE_CURVE"
keyword_prefix = "DEFINE_CURVE"
field = "lcid"
evidence = "torture table_ids (curves 5, 6 named by table rows)"

[[definer]]
kind = "DEFINE_TABLE"
keyword_prefix = "DEFINE_TABLE"
field = "tbid"
evidence = "torture table_ids (lcss 10 = *DEFINE_TABLE 10)"

[[definer]]
kind = "SET_PART"
keyword_prefix = "SET_PART"
field = "sid"
evidence = "torture part_inertia (contact ssid 1, sstyp 2 = *SET_PART_LIST 1)"

[[definer]]
kind = "SET_NODE"
keyword_prefix = "SET_NODE"
field = "sid"
evidence = "torture spc_set_id (nsid 1 = *SET_NODE_LIST 1)"

[[definer]]
kind = "SET_SEGMENT"
keyword_prefix = "SET_SEGMENT"
field = "sid"
evidence = "data: every SET_SEGMENT* first card is sid; corpus run checks"

[[definer]]
kind = "SET_SOLID"
keyword_prefix = "SET_SOLID"
field = "sid"
evidence = "data: sid first; corpus run checks"

[[definer]]
kind = "SET_BEAM"
keyword_prefix = "SET_BEAM"
field = "sid"
evidence = "data: sid first; corpus run checks"

[[definer]]
kind = "SET_DISCRETE"
keyword_prefix = "SET_DISCRETE"
field = "sid"
evidence = "data: sid first; corpus run checks"

[[definer]]
kind = "DEFINE_BOX"
keyword_prefix = "DEFINE_BOX"
field = "boxid"
evidence = "data: boxid first; corpus run checks"

[[definer]]
kind = "DEFINE_VECTOR"
keyword_prefix = "DEFINE_VECTOR"
field = "vid"
evidence = "data: vid first; corpus run checks"

[[definer]]
kind = "DEFINE_COORDINATE_SYSTEM"
keyword_prefix = "DEFINE_COORDINATE"
field = "cid"
evidence = "data: DEFINE_COORDINATE_SYSTEM/_NODES/_VECTOR all start with cid; corpus run checks"

[[definer]]
kind = "DEFINE_TRANSFORMATION"
keyword = "DEFINE_TRANSFORMATION"
field = "tranid"
evidence = "Yaris combine.key:101 (*INCLUDE_TRANSFORM tranid; M1a check)"

[[definer]]
kind = "ELEMENT_SHELL"
keyword_prefix = "ELEMENT_SHELL"
field = "eid"
evidence = "torture base"

[[definer]]
kind = "ELEMENT_SOLID"
keyword_prefix = "ELEMENT_SOLID"
field = "eid"
evidence = "data: eid first; corpus run checks"

[[definer]]
kind = "ELEMENT_BEAM"
keyword_prefix = "ELEMENT_BEAM"
field = "eid"
evidence = "data: eid first; corpus run checks"

[[family]]
kind = "NODE"
prefix = "NODE"

[[family]]
kind = "PART"
prefix = "PART"

[[family]]
kind = "MAT"
prefix = "MAT"

[[family]]
kind = "SECTION"
prefix = "SECTION"

[[family]]
kind = "DEFINE_CURVE"
prefix = "DEFINE_CURVE"

[[family]]
kind = "DEFINE_TABLE"
prefix = "DEFINE_TABLE"

[[family]]
kind = "SET_PART"
prefix = "SET_PART"

[[family]]
kind = "SET_NODE"
prefix = "SET_NODE"

[[family]]
kind = "SET_SEGMENT"
prefix = "SET_SEGMENT"

[[family]]
kind = "SET_SOLID"
prefix = "SET_SOLID"

[[family]]
kind = "SET_BEAM"
prefix = "SET_BEAM"

[[family]]
kind = "SET_DISCRETE"
prefix = "SET_DISCRETE"

[[family]]
kind = "DEFINE_BOX"
prefix = "DEFINE_BOX"

[[family]]
kind = "DEFINE_VECTOR"
prefix = "DEFINE_VECTOR"

[[family]]
kind = "DEFINE_COORDINATE_SYSTEM"
prefix = "DEFINE_COORDINATE"

[[family]]
kind = "ELEMENT_SHELL"
prefix = "ELEMENT_SHELL"

[[family]]
kind = "ELEMENT_SOLID"
prefix = "ELEMENT_SOLID"

[[family]]
kind = "ELEMENT_BEAM"
prefix = "ELEMENT_BEAM"
```

The table's evidence lines that cite Task 1 must match Task 1's verdicts. If a cited case was rejected for a reason
touching the row, fix the row and its evidence.

- [ ] **Step 2: Write the failing definer tests**

Create `tests/test_definers.py`:

```python
from deckcheck.definers import definers, family_kind, not_definer
from deckcheck.keywords import layout, walk_cards


def test_every_row_reaches_a_keyword_with_its_field():
    import tomllib
    from importlib import resources
    from deckcheck.keywords import override_targets
    rows = tomllib.loads(resources.files("deckcheck.data").joinpath("definers.toml").read_text(encoding="utf-8"))
    for row in rows["definer"]:
        assert any(row["field"] in {f["name"] for c in walk_cards(layout(k)["cards"]) for f in c.get("fields", [])}
                   for k in override_targets(row)), row["kind"]


def test_core_definers():
    d = definers()
    assert ("PART", "pid") in d["PART"] and ("PART", "pid") in d["PART_INERTIA"]
    assert ("MAT", "mid") in d["MAT_ELASTIC"]
    assert "MAT_ADD_EROSION" not in d
    assert ("SECTION", "secid") in d["SECTION_SHELL"]
    assert ("ICFD_PART", "pid") in d["ICFD_PART"]  # from overrides.toml set.defines


def test_family_kind():
    assert family_kind("SET_PART_TITLE") == "SET_PART"
    assert family_kind("PART_MOVE") == "PART"
    assert family_kind("PARTITION") is None
    assert family_kind("DEFINE_COORDINATE_NODES") == "DEFINE_COORDINATE_SYSTEM"
    assert family_kind("CONTROL_TERMINATION") is None


def test_not_definer():
    assert not_definer("MAT_ADD_EROSION") and not not_definer("MAT_ELASTIC")
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_definers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.definers'`.

- [ ] **Step 4: Write `definers.py`**

```python
"""Which keywords define which entity kinds (data/definers.toml, plus ICFD_PART from overrides.toml), and the
families whose unknown members make a kind uncertain (docs/m1a-keyword-data.md §4.1)."""
import functools
import tomllib
from importlib import resources

from deckcheck.keywords import layout, load, override_targets, overrides, walk_cards


@functools.cache
def _table() -> dict:
    return tomllib.loads(resources.files("deckcheck.data").joinpath("definers.toml").read_text(encoding="utf-8"))


def _fields(key: str) -> set[str]:
    return {f["name"] for c in walk_cards(layout(key)["cards"]) for f in c.get("fields", [])}


@functools.cache
def definers() -> dict[str, tuple[tuple[str, str], ...]]:
    rows = [(r, r["kind"], r["field"]) for r in _table()["definer"]]
    rows += [(o, o["set"]["defines"], o["field"]) for o in overrides()["override"] if "defines" in o["set"]]
    out: dict[str, list[tuple[str, str]]] = {}
    for row, kind, field in rows:
        for key in override_targets(row):
            if key in load()["keywords"] and field in _fields(key) and not not_definer(key):
                out.setdefault(key, []).append((kind, field))
    return {k: tuple(v) for k, v in out.items()}


def not_definer(name: str) -> bool:
    return any(name == p or (p.endswith("_") and name.startswith(p)) for p in _table()["not_definers"])


@functools.cache
def family_kind(name: str) -> str | None:
    best = None
    for fam in _table()["family"]:
        p = fam["prefix"]
        if (name == p or name.startswith(p + "_")) and (best is None or len(p) > len(best[0])):
            best = (p, fam["kind"])
    return best[1] if best else None
```

- [ ] **Step 5: Run the definer tests**

Run: `.venv/Scripts/python -m pytest tests/test_definers.py -q`
Expected: 4 PASS. If `PART_CONTACT` or `PART_COMPOSITE` has no `pid` field in the data, the first test still passes
(the row reaches `PART`). Note it in the ledger; the family rule then covers those keywords.

- [ ] **Step 6: Write the index tests**

Add `[index]` to the three seeded cases' `expected.toml`. For `seeded_mistakes`:
- the PART 1 card is line 8 (`mid` 99 at columns 28–30);
- the second PART card is line 11 (`pid` 1 at 9–10).

```toml
[index]
dangling = [{kind = "MAT", id = 99, file = "main.k", line = 8, columns = [28, 30]}]
duplicates = [{kind = "PART", id = 1, file = "main.k", line = 11, columns = [9, 10]}]
```

Check `crlf_seeded` and `latin1_seeded` with `grep -n` for their own line numbers and write theirs.

`test_torture_index` runs **every** torture case, so every rejected case needs an `[index]` table, including M1b's
`inc_nested_sibling`, `inc_nested_both`, `inc_path_precedence`, `inc_path_relative`, `inc_path_late` and `inc_cycle`.
Write each table from that case's LS-DYNA deciding line in `bakeoff/results/m1b_referee.txt`:
- `MAT 1 is not found` becomes a `MAT` 1 entry at the `mid` field of the part card;
- a cycle whose model is complete gets an empty table.

Where LS-DYNA's complaint is something the index cannot see, write an empty table with a `note_index` line naming
the M1d check that covers it. For example, `tabs`: the tab makes `mid` a `bad` value, and DC003 reports it. Write
these tables before running the index, from LS-DYNA's words, never from the index's output.

Create `tests/test_index.py`:

```python
import os
import tomllib
from pathlib import Path

import pytest

from deckcheck.includes import resolve_tree
from deckcheck.index import OFFSET_FIELD, build, pack, unpack
from deckcheck.keywords import layout, walk_cards

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))


def i10(*vals):
    return "".join(f"{v:>10}" for v in vals)


BASE = ("*PART\nplate\n" + i10(1, 1, 1) + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n" + i10(1.0, 1.0, 1.0, 1.0) + "\n"
        "*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n")


def index(tmp_path, body, files=None):
    (tmp_path / "main.k").write_bytes(("*KEYWORD\n" + body + "*END\n").encode("latin-1"))
    for rel, text in (files or {}).items():
        (tmp_path / rel).write_bytes(text.encode("latin-1"))
    return build(resolve_tree(tmp_path / "main.k"))


def dangling(ix, root):
    return [{"kind": r.kind, "id": r.id, "file": r.path.relative_to(root).as_posix(), "line": r.line,
             "columns": [r.start, r.end]} for r in ix.dangling()]


def duplicates(ix, root):
    return [{"kind": d.kind, "id": d.id, "file": d.path.relative_to(root).as_posix(), "line": d.line,
             "columns": [d.start, d.end]} for d in ix.duplicates()]


@pytest.mark.parametrize("case", CASES)
def test_torture_index(case):
    expected = tomllib.loads((TORTURE / case / "expected.toml").read_text(encoding="utf-8"))
    table = expected.get("index", {})
    root = Path(os.path.abspath(TORTURE / case))  # the resolver's paths are abspath+normpath, never resolve()
    ix = build(resolve_tree(TORTURE / case / "main.k"))
    assert dangling(ix, root) == table.get("dangling", [])
    assert duplicates(ix, root) == table.get("duplicates", [])


def test_seeded_unused_material():
    ix = build(resolve_tree(TORTURE / "seeded_mistakes" / "main.k"))
    assert 7 not in ix.used("MAT") and 99 in ix.used("MAT")


def test_zero_and_blank_are_no_reference(tmp_path):
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, 1, 0, 0, 0, 0, 0)))
    assert ix.dangling() == [] and ix.used("HOURGLASS") == set()


def test_negative_plain_link_is_a_possible_use_not_a_reference(tmp_path):
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, -5)))
    assert ix.dangling() == [] and 5 in ix.used("MAT")


def card_text(key, **values):
    """A fixed-format card holding `values`, laid out by the first card of `key` that has all their fields."""
    for card in walk_cards(layout(key)["cards"]):
        spec = {f["name"]: f for f in card.get("fields", [])}
        if values.keys() <= spec.keys():
            line = [" "] * 80
            for name, v in values.items():
                f = spec[name]
                line[f["offset"]:f["offset"] + f["width"]] = str(v).rjust(f["width"])
            return "".join(line).rstrip()
    raise KeyError(values)


def test_negative_cn_is_a_curve_reference(tmp_path):
    body = ("*AIRBAG_SIMPLE_PRESSURE_VOLUME\n" + card_text("AIRBAG_SIMPLE_PRESSURE_VOLUME", sid=1) + "\n"
            + card_text("AIRBAG_SIMPLE_PRESSURE_VOLUME", cn=-1) + "\n")
    ix = index(tmp_path, body)
    assert ("DEFINE_CURVE", 1) in {(r.kind, r.id) for r in ix.dangling()}


def test_link_by_type_value(tmp_path):
    contact = "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(5, 0, "{t}", 0) + "\n" + i10(0.0) + "\n" + i10(1.0) + "\n"
    assert [(r.kind, r.id) for r in index(tmp_path, BASE + contact.format(t=2)).dangling()] == [("SET_PART", 5)]
    assert index(tmp_path, BASE + contact.format(t=0)).dangling() == []  # type 0 is unmapped: unchecked


def test_unresolved_family_member_makes_kind_uncertain(tmp_path):
    contact = "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + i10(5, 0, 2, 0) + "\n" + i10(0.0) + "\n" + i10(1.0) + "\n"
    ix = index(tmp_path, BASE + contact + "*SET_PART_TITLE\nnamed set\n" + i10(5) + "\n" + i10(1) + "\n")
    assert ix.dangling() == [] and "SET_PART" in ix.uncertain_defs and not ix.checked("SET_PART")


def test_unread_block_makes_its_kinds_uncertain(tmp_path):
    body = BASE.replace(i10(1, 1, 1), i10(1, 99, 1)).replace(
        "*SECTION_SHELL\n" + i10(1, 2), "*SECTION_SHELL\n" + i10(1, 2, 1.0, 3, 0.0, 0, "&undef"))
    ix = index(tmp_path, body)
    assert ix.dangling() == [] and "SECTION" in ix.uncertain_defs
    assert any(p.kind == "unread" for _, p in ix.problems)


def test_parameter_in_id_field(tmp_path):
    ix = index(tmp_path, "*PARAMETER\nI mm               1\n" + BASE.replace(i10(1, 1, 1), i10(1, 1, "&mm")))
    assert ix.dangling() == [] and 1 in ix.used("MAT")
    ix = index(tmp_path, BASE.replace(i10(1, 1, 1), i10(1, 1, "&nope")))
    assert ix.dangling() == [] and "MAT" in ix.uncertain_uses


def transform(offsets: dict) -> str:
    order = ["idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff", "iddoff"]
    return ("*INCLUDE_TRANSFORM\nsub.k\n" + i10(*(offsets.get(f, 0) for f in order)) + "\n"
            + i10(offsets.get("idroff", 0)) + "\n\n\n")


@pytest.mark.skipif("MAT" not in OFFSET_FIELD, reason="LS-DYNA did not decide the material offset")
def test_transform_offset_shifts_definitions(tmp_path):
    sub = "*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"
    body = transform({OFFSET_FIELD["MAT"]: 100}) + BASE.replace(i10(1, 1, 1), i10(1, 1, 101)).split("*MAT_ELASTIC")[0]
    ix = index(tmp_path, body, {"sub.k": sub})
    assert ix.dangling() == [] and 101 in ix.defs["MAT"]


@pytest.mark.skipif("MAT" not in OFFSET_FIELD, reason="LS-DYNA did not decide the material offset")
def test_same_file_two_transforms(tmp_path):
    sub = "*KEYWORD\n*MAT_ELASTIC\n" + i10(1, "7.85E-9", "210000.0", 0.3) + "\n*END\n"
    f = OFFSET_FIELD["MAT"]
    ix = index(tmp_path, transform({f: 100}) + transform({f: 200}) + BASE, {"sub.k": sub})
    assert ix.duplicates() == [] and {1, 101, 201} <= set(ix.defs["MAT"])


def test_unrefereed_offset_makes_kind_uncertain(tmp_path):
    sub = "*KEYWORD\n*DEFINE_BOX\n" + i10(1, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0) + "\n*END\n"
    ix = index(tmp_path, transform({f: 7 for f in ("idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff",
                                                   "iddoff", "idroff")}) + BASE, {"sub.k": sub})
    if "DEFINE_BOX" not in OFFSET_FIELD:
        assert "DEFINE_BOX" in ix.uncertain_defs


def test_unfollowed_include_blinds_the_index(tmp_path):
    ix = index(tmp_path, "*INCLUDE_AUTO_OFFSET\nother.k\n" + BASE.replace(i10(1, 1, 1), i10(1, 1, 99)))
    assert ix.blind and ix.dangling() == []


def test_missing_include_does_not_blind(tmp_path):
    ix = index(tmp_path, "*INCLUDE\nnot_there.k\n" + BASE.replace(i10(1, 1, 1), i10(1, 1, 99)))
    assert [(r.kind, r.id) for r in ix.dangling()] == [("MAT", 99)]


def test_pack_roundtrip():
    for loc in [(0, 1, 0, 0), (3, 2**20 + 5, 1500, 1600), (65535, 2**31 - 1, 65535, 65535)]:
        assert unpack(pack(*loc)) == loc
```

- [ ] **Step 7: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_index.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'deckcheck.index'`.

- [ ] **Step 8: Write `index.py`**

Fill `OFFSET_FIELD` from `bakeoff/results/m1c_probes.json`, one line per decided kind, naming the probe. The
values below are placeholders for the shape, to be replaced by the probe results. A kind left out is uncertain in
any file with nonzero offsets.

```python
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
    "MAT": "idmoff",  # replace from m1c_probes.json: offsets.MAT.decided
}
# a reference of the key kind resolves against definitions of any listed kind (curves and tables share ids)
LOOKUP = {"DEFINE_CURVE": ("DEFINE_CURVE", "DEFINE_TABLE"), "DEFINE_CURVE_OR_TABLE": ("DEFINE_CURVE", "DEFINE_TABLE")}
STRUCTURAL = frozenset({"KEYWORD", "TITLE", "END"})


def pack(file: int, line: int, start: int, end: int) -> int:
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
            return LONG_KEYWORD and "LONG=S" in line.upper().replace(" ", "")
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
    refs: dict[str, tuple[array, array, array]] = field(default_factory=dict)
    possible: dict[str, set[int]] = field(default_factory=dict)
    uncertain_defs: dict[str, set[str]] = field(default_factory=dict)
    uncertain_uses: dict[str, set[str]] = field(default_factory=dict)
    blind: set[str] = field(default_factory=set)
    problems: list[tuple[int, FieldProblem]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    _name_ids: dict[str, int] = field(default_factory=dict)

    def where(self, loc: int) -> tuple[Path, int, int, int]:
        f, line, start, end = unpack(loc)
        return self.tree.files[f].path, line, start, end

    def checked(self, kind: str) -> bool:
        return not self.blind and not any(k in self.uncertain_defs for k in LOOKUP.get(kind, (kind,)))

    def dangling(self) -> list[Ref]:
        out = []
        for kind, (ids, locs, names) in self.refs.items():
            if not self.checked(kind):
                continue
            targets = [self.defs.get(k, {}) for k in LOOKUP.get(kind, (kind,))]
            for i, id_ in enumerate(ids):
                if not any(id_ in t for t in targets):
                    out.append(Ref(kind, id_, *self.where(locs[i]), self.names[names[i]]))
        return sorted(out, key=lambda r: (str(r.path), r.line, r.start))

    def duplicates(self) -> list[Dup]:
        return [Dup(kind, id_, *self.where(loc), *self.where(first)[:2]) for kind, id_, loc, first in self.dups]

    def used(self, kind: str) -> set[int]:
        out: set[int] = set()
        for k, (ids, _, _) in self.refs.items():
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
            self._uncertain(self.uncertain_defs, kind, f"{f.line}: id not known")
            return
        if not isinstance(f.value, int) or f.value <= 0:
            return
        shift = _shift(kind, offs)
        if shift is None:
            self._uncertain(self.uncertain_defs, kind, "transform offset not refereed")
            return
        id_, loc = f.value + shift, pack(fi, f.line, f.start, f.end)
        seen = self.defs.setdefault(kind, {})
        if id_ in seen:
            self.dups.append((kind, id_, loc, seen[id_]))
        else:
            seen[id_] = loc

    def _reference(self, f: Field, row: dict[str, Field], fi: int, offs, key: str) -> None:
        spec, v = f.spec, f.value
        if "link_by" in spec:
            t = row.get(spec["link_by"])
            kind = spec["link_map"].get(str(t.value)) if t is not None and isinstance(t.value, int) else None
        else:
            kind = spec.get("link")
        if kind is None or v is None or v == 0:
            return
        if v is UNKNOWN:
            self._uncertain(self.uncertain_uses, kind, f"{f.line}: reference not known")
            return
        if not isinstance(v, int):
            return
        shift = _shift(kind, offs)
        if shift is None:
            self._uncertain(self.uncertain_uses, kind, "transform offset not refereed")
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
        ids, locs, names = self.refs.setdefault(kind, (array("q"), array("q"), array("H")))
        ids.append(v + shift)
        locs.append(pack(fi, f.line, f.start, f.end))
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
            if name in STRUCTURAL or name.startswith(("INCLUDE", "PARAMETER")):
                continue
            key = block.resolved.name if block.resolved else None
            kinds = definers().get(key, ()) if key else ()
            fam = family_kind(key or name)
            if fam and not any(k == fam for k, _ in kinds) and not not_definer(key or name):
                ix._uncertain(ix.uncertain_defs, fam, f"*{name} defines {fam}s deckcheck can't read")
            if key is None or not _wanted(key):
                continue
            problems: list[FieldProblem] = []
            fields = read_fields(block, params, long_deck, _wanted(key), problems)
            for _, group in itertools.groupby(fields, key=attrgetter("group")):
                row = list(group)
                by = {f.name: f for f in row}
                for f in row:
                    for kind, idf in kinds:
                        if f.name == idf:
                            ix._define(kind, f, fi, offs)
                    ix._reference(f, by, fi, offs, key)
            for p in problems:
                ix.problems.append((fi, p))
                if p.kind == "unread":
                    for kind, _ in kinds:
                        ix._uncertain(ix.uncertain_defs, kind, f"{node.path.name}:{p.line} unread")
                    for kind in _link_kinds(key):
                        ix._uncertain(ix.uncertain_uses, kind, f"{node.path.name}:{p.line} unread")
    return ix
```

Notes on the design:
- **Row grouping.** `group` changes per card read, so a `link_by` type field must sit on the same card as its id
  field. That holds for every `link_by` override (contact first card, velocity first card).
- **Files whose transform is unread.** The resolver reports `unread` for long-format transforms. Those files'
  offsets are unknown, so the index is blind.
- **Missing includes don't blind.** Spec §4: the rest of the deck is still checked. M1d may word DC001's message
  around a tree with missing files.

- [ ] **Step 9: Run the index tests**

Run: `.venv/Scripts/python -m pytest tests/test_index.py tests/test_definers.py -q`
Expected: all PASS.

`test_torture_index` runs every torture case: each accepted case must have no dangling reference and no duplicate,
and each rejected case must match its hand-located `[index]` table. A failure on an accepted case is a false
alarm. Find its mechanism (layout, definer row, override, reading rule), fix it test-first with the case as the
test, and ledger it. Never edit an accepted case's table to fit the index.

- [ ] **Step 10: Run the whole fast suite**

Run: `.venv/Scripts/python -m pytest -q -m "not extract and not lsdyna and not corpus"`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/deckcheck/data/definers.toml src/deckcheck/definers.py src/deckcheck/index.py tests/test_definers.py tests/test_index.py tests/torture
git commit -m "M1c Task 6: definer table and index (offsets, sign rules, uncertain kinds)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The corpus gate and the report

**Files:**
- Create: `bakeoff/index_tree.py`, `bakeoff/m1c_corpus.py`, `bakeoff/results/m1c_index.jsonl`,
  `tests/corpus/expected_index.toml`, `tests/test_index_corpus.py`, `docs/m1c-field-reader-index.md`
- Modify: `src/deckcheck/data/definers.toml` and `overrides.toml` (rows the corpus proves, each with evidence),
  `docs/specs/2026-10-27-deckcheck-design.md` (§4 index row, §9 layout, §11 progress)

**Interfaces:**
- Consumes: `index.build`; `bakeoff.run.run_one(deck, cap_mb, module=...)`; `bakeoff/results/tier1_lsdyna_input.jsonl`
  (M0 verdicts: which tier-1 decks LS-DYNA accepts).
- Produces:
  - `tests/corpus/expected_index.toml`: per deck, the dangling references and duplicates judged real, each with
    its evidence. M1d's DC001/DC002 corpus expectations start from it.
  - The M1c report.

- [ ] **Step 1: Write the child-process summary**

Create `bakeoff/index_tree.py`:

```python
"""Index one deck with deckcheck and write a summary JSON: python -m bakeoff.index_tree <deck> <out>."""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from deckcheck.includes import resolve_tree
from deckcheck.index import build

deck, out = Path(sys.argv[1]), Path(sys.argv[2])
start = time.monotonic()
tree = resolve_tree(deck)
ix = build(tree)
root = os.path.dirname(os.path.abspath(deck))


def rel(p):
    return Path(os.path.relpath(p, root)).as_posix()


dangling, dups = ix.dangling(), ix.duplicates()
out.write_text(json.dumps({
    "deck": str(deck),
    "files": len(tree.files),
    "defs": {k: len(v) for k, v in sorted(ix.defs.items())},
    "refs": {k: len(v[0]) for k, v in sorted(ix.refs.items())},
    "dangling_total": len(dangling),
    "dangling": [{"kind": r.kind, "id": r.id, "file": rel(r.path), "line": r.line, "field": r.field}
                 for r in dangling[:100]],
    "duplicates_total": len(dups),
    "duplicates": [{"kind": d.kind, "id": d.id, "file": rel(d.path), "line": d.line,
                    "first": f"{rel(d.first_path)}:{d.first_line}"} for d in dups[:100]],
    "blind": sorted(ix.blind),
    "uncertain_defs": {k: sorted(v)[:5] for k, v in sorted(ix.uncertain_defs.items())},
    "uncertain_uses": {k: sorted(v)[:5] for k, v in sorted(ix.uncertain_uses.items())},
    "problems": dict(Counter(p.kind for _, p in ix.problems)),
    "problem_examples": [{"file": rel(tree.files[fi].path), "line": p.line, "kind": p.kind, "detail": p.detail}
                         for fi, p in ix.problems[:20]],
    "seconds": round(time.monotonic() - start, 1),
}), encoding="utf-8")
```

Create `bakeoff/m1c_corpus.py`, the same shape as `bakeoff/m1b_corpus.py`:

```python
"""M1c corpus run: deckcheck's index on every deck, each in a child process under 2 GB."""
import json
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST, TORTURE, run_one

OUT = Path("bakeoff/results/m1c_index.jsonl")

if __name__ == "__main__":
    decks = [(p.parent.name, p) for p in sorted(TORTURE.glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(MANIFEST)]
    with open(OUT, "w", encoding="utf-8") as f:
        for name, deck in decks:
            row = {"name": name, **run_one(deck, cap_mb=2048, timeout_s=900, module="bakeoff.index_tree")}
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(name, row.get("error") or f"dangling {row['dangling_total']}, dup {row['duplicates_total']}, "
                  f"problems {row['problems']}", row["peak_mb"], row.get("seconds"))
```

- [ ] **Step 2: Run the corpus**

Run: `.venv/Scripts/python -m bakeoff.m1c_corpus`
Expected:
- one line per deck (63 decks);
- no `error` (memory cap or crash);
- Yaris peak under 2048 MB. The estimate is about 1.3 GB: 683 MB of cards plus about 300 MB of definitions plus
  about 250 MB of reference arrays.

Record each deck's seconds. A deck over the cap is a stop: profile where the memory goes, rule on the smallest fix
(for example dropping `possible` for kinds M1d won't report), rerun, and ledger it.

- [ ] **Step 3: Judge every dangling reference, duplicate and problem**

For each deck LS-DYNA accepted, every dangling reference and duplicate is a false alarm until shown otherwise.
LS-DYNA's acceptance comes from:
- the torture `lsdyna_valid`;
- M0's `tier1_lsdyna_input.jsonl` for tier 1;
- the 18-file load for VIVA+;
- the Yaris, which LS-DYNA Student could not referee: there, "unexplained" means not traced to deck text.

For each finding, find the mechanism and fix it test-first:
- a definer row or `not_definers` entry, with the corpus line as evidence;
- an override;
- a reading rule (backed by a new torture case and LS-DYNA run).

The test is either a torture case or a unit test in `test_index.py`/`test_fields.py` reproducing the deck text.

Every `unread`, `extra` and `bad` problem gets the same treatment. Tally them by keyword and decide each group:
- a layout fix;
- an override;
- a stop that is correct and stays (with reason).

Findings judged **real** go into `tests/corpus/expected_index.toml`, keyed by manifest name:

```toml
# Index findings on corpus decks judged real (M1c Task 7). Each cites its evidence.
[[deck]]
name = "lsdyna-doc-guidelines-implicit-bolts001"
dangling = []
duplicates = []
evidence = "..."
```

Rerun Step 2 after each batch of fixes. The gate: zero unexplained dangling references, duplicates and problems on
every deck LS-DYNA accepts, with every uncertain kind's reason listed in the report. Record the
uncertain-kind tally per deck: an index that is "clean" because everything is uncertain has not passed. If a kind
is uncertain on most corpus decks, the report says so and the fix (definer rows, refereed offsets) is part of
this step, not deferred.

- [ ] **Step 4: Pin the corpus result as a test**

Create `tests/test_index_corpus.py`:

```python
import tomllib
from pathlib import Path

import pytest

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST
from deckcheck.includes import resolve_tree
from deckcheck.index import build

pytestmark = pytest.mark.corpus
EXPECTED = {d["name"]: d for d in tomllib.loads(
    (Path(__file__).parent / "corpus" / "expected_index.toml").read_text(encoding="utf-8"))["deck"]}
SMALL = [e for e in load_manifest(MANIFEST) if e.tier == 1]


@pytest.mark.parametrize("entry", SMALL, ids=lambda e: e.name)
def test_tier1_index_matches_judged_findings(entry):
    ix = build(resolve_tree(fetch(entry)))
    want = EXPECTED.get(entry.name, {"dangling": [], "duplicates": []})
    assert [(r.kind, r.id, r.path.name, r.line) for r in ix.dangling()] == [
        (d["kind"], d["id"], d["file"], d["line"]) for d in want["dangling"]]
    assert [(d.kind, d.id, d.path.name, d.line) for d in ix.duplicates()] == [
        (d["kind"], d["id"], d["file"], d["line"]) for d in want["duplicates"]]


def test_icfd_parts_are_their_own_namespace():
    entry = [e for e in SMALL if "main_fsi" in e.name][0]
    ix = build(resolve_tree(fetch(entry)))
    assert ix.defs.get("ICFD_PART") and "ICFD_PART" not in {r.kind for r in ix.dangling()}
```

`file` in `expected_index.toml` is the file's basename. VIVA+ and the Yaris stay in the capped bakeoff run (Step 2),
because a pytest process has no memory cap.

Run: `.venv/Scripts/python -m pytest tests/test_index_corpus.py -q -m corpus`
Expected: PASS for every tier-1 deck.

- [ ] **Step 5: Write the report and update the spec**

Create `docs/m1c-field-reader-index.md`, in M1b's form:
1. **Verdict.**
2. **What LS-DYNA decided:** the 15 cases and the offset probes. Table: case, question, verdict, deciding line,
   rule adopted.
3. **Extraction v2:** counts of conditions, lengths and `"?"`, and the refused expressions.
4. **Corpus:** a table per tier with decks, definitions, references, dangling (real), duplicates (real), problems
   by kind, uncertain kinds, peak MB and slowest deck. Then every fix the corpus forced, with its evidence.
5. **Spec §11 progress:** the seven M0 defects, each with its test name.
6. **What this means for M1d:**
   - which kinds DC005 can report (tracked uses, few uncertain);
   - how DC001 words a finding in a tree with missing includes;
   - DC003's inputs (`extra`, `bad`, tabs);
   - the open reading rules (unrefereed offsets, nested transforms, long-format series).

In the spec:
- §4 index row: add the definer table (`data/definers.toml`), uncertain kinds, and `*PARAMETER` through
  `deckcheck.params`.
- §9 layout: add `conditions.py`, `params.py`, `definers.py`.
- §11: add an M1c progress note.

- [ ] **Step 6: Update the living report**

Update the living report (Claude Docs container `48f8b66d-9da0-4b78-8800-d07e403e0761`):
- the status line (M1c done, M1d next);
- the architecture diagram (node `e5f3e61e-9292`). Replace the stale dynars diagram with the B1′ pipeline:
  reader → include resolver → field reader (conditions, params) → index (definers) → rules (M1d) → front doors.

- [ ] **Step 7: Run everything**

Run: `.venv/Scripts/python -m pytest -q -m "not extract" && .venv-extract/Scripts/python -m pytest -q -m extract tests/test_extract.py`
Expected: all PASS. `lsdyna`-marked tests run where the install is present, and `corpus` tests where the decks are.

- [ ] **Step 8: Commit**

```bash
git add bakeoff/index_tree.py bakeoff/m1c_corpus.py bakeoff/results/m1c_index.jsonl tests/corpus/expected_index.toml tests/test_index_corpus.py docs/m1c-field-reader-index.md docs/specs/2026-10-27-deckcheck-design.md src/deckcheck/data
git commit -m "M1c Task 7: corpus gate and report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
