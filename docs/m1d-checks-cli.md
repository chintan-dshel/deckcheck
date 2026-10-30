# M1d: checks, command line, packaging

Branch `m1d`, plan `docs/plans/2026-10-29-m1d-checks-cli.md`, spec `docs/specs/2026-10-27-deckcheck-design.md`
(revised for M1d). M1d turns M1c's index into a command an engineer runs: `deckcheck model.k` prints DC000–DC006
at exact lines and columns, then a "Not checked" footer, as text or JSON, with exit codes for CI.

## 1. What LS-DYNA decided

LS-DYNA R16.1 Student, 2026-10-29 (`bakeoff/results/m1d_referee.txt`). Every case is a torture deck under
`tests/torture/`.

| Case | Question | Verdict | Consequence |
|---|---|---|---|
| `m1d_bpm_set_none`, `m1d_load_node_set_none`, `m1d_load_segment_set_none`, `m1d_initial_velocity_none`, `m1d_history_node_set_none` | Is a missing set accepted, as for `*BOUNDARY_SPC_SET`? | All rejected, Error 10144 ("node set ... # 99 is not found") | DC001. DC006 covers `*BOUNDARY_SPC_SET` only. |
| `m1d_dup_part`, `_mat`, `_section`, `_curve`, `_node_set` | Is a duplicate id accepted? | All rejected (Errors 10176, 10137, 10137, 10173, 10110) | DC002 error |
| `m1d_dup_node` | Duplicate node, different coordinates | Rejected, Error 11168 "Duplicate node ID 1 with non-matching coordinates" | DC002 error |
| `m1d_dup_node_same` | Duplicate node, same coordinates | Accepted, no warning | DC002 warning. deckcheck compares the two cards' coordinates. |
| `m1d_overflow_node` | A 9-digit node id in the 8-wide field | Accepted, **misread**: d3hsp shows node 12345678 at x = 95.0 (the deck says 5.0) | Class 2, not detected in M1 (needs every field of the card read; M4) |
| `m1d_mixed_free` | Two values in one comma slot | Accepted, read correctly (E = 2.1E+05, ν = 0.3) | Not a finding; removed from DC003 |
| `m1d_umat` | `*MAT_USER_DEFINED_MATERIAL_MODELS` (umat41) | Accepted | deckcheck reads it: MAT 2 defined and used |
| `inc_multi_missing` | Does LS-DYNA report every missing name on one `*INCLUDE`? | Only the first (Error 10087) | DC004 still reports every missing name: each is a file the engineer must supply |

## 2. DC005 audit

`tests/test_dc005_audit.py` scans the keyword data for fields whose name looks like a reference to MAT, SECTION or
HOURGLASS (`mid`, `mid1`, `matid`, `secid`, `hgid`, …) but carries no link, outside the kind's own definers. It
found 63 fields in 25 keywords; HOURGLASS had none. Each one is recorded in `src/deckcheck/data/dc005_audit.toml`:
- **61 are another id space**: CESE, DUALCESE, ICFD and battery materials, ICFD sections, mode numbers, and a BEM
  matrix selector. pydyna's help text is the reason in each case.
- **2 are undecided**: `*EM_EP_CELLMODEL_TOMEK` `matid` and `*EM_EP_CELLMODEL_USERMAT` `mid`. pydyna says they
  refer to the part's material, but no LS-DYNA case has confirmed it. DC005 stays silent on MAT in any deck
  containing them.

The test fails if a new look-alike field appears without a verdict.

## 3. Corpus gate

`bakeoff/m1d_corpus.py` runs the real checks on every deck, each in its own process under a 2 GB cap
(`bakeoff/results/m1d_lint.jsonl`).

| Tier | Decks | Findings | Peak memory |
|---|---|---|---|
| 1 (LS-DYNA documentation) | 35 | DC001 632 (`tensile_test`, the M1c finding), DC004 6 (M1b's real missing includes), DC005 4 | ≤ 194 MB |
| 2 VIVA+ | 1 (18 files) | none; DC005 silent (50 `*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED_TITLE` blocks aren't in the keyword data) | 548 MB, 18.5 s |
| 2 Yaris | 1 (4 files) | none; DC005 fully checked: no unused material, section or hourglass control | 1,144 MB, 63 s |

There were no DC000, DC003 or DC006 findings on the corpus. The four DC005 findings were judged from every place
that could refer to the kind (each deck's `*PART` cards), not by searching the text for the number: ids 1 and 2
appear on thousands of element lines. The evidence is in `tests/corpus/expected_diagnostics.toml`:
- `B4_Postbuckling_Frame.key` MAT 1 and MAT 2: both parts use material 100.
- `spr4.k` SECTION 2: all six parts use section 1.
- `set_4.key` MAT 1: the parts use materials 3 and 2.

## 4. Spec §11, M1 done

| Criterion | Evidence |
|---|---|
| Keyword data checked for the M0 defect keywords | M1a/M1c (`docs/m1c-field-reader-index.md` §4) |
| DC001–DC006 catch their seeded mistakes, with exact diagnostics | `tests/test_rules.py::test_torture_diagnostics` (72 cases × 7 codes) |
| LS-DYNA decided DC006 sets, DC002 severity, DC003 scope | §1 above, `bakeoff/results/m1d_referee.txt` |
| DC005 audit done | `tests/test_dc005_audit.py` |
| User-defined material read or not checked, never false | `test_umat_part_material_is_not_reported` |
| The seven M0 defects pass | M1c |
| Exact line and column on all torture decks | the torture harness compares columns |
| Zero unexplained diagnostics on tier 1, VIVA+ and the Yaris under 2 GB | §3, `tests/test_rules_corpus.py`, `tests/test_index_corpus.py` |
| Clean `pip install` with no runtime dependencies | `tests/test_install.py` (marker `install`) |
| CLI text and JSON documented in the README | `README.md` |
| PyPI only with Chintan's explicit yes | not published |

## 5. What this means for M2

- The language server can call `deckcheck.rules.check(main)` and map each `Diagnostic` directly. Columns are
  0-based with an exclusive end, which is the LSP convention. `Related` becomes related information.
- JSON `version` 1 is the contract for scripts. A breaking change bumps it.
- "Not checked" needs a home in the editor: a status-bar note or an information diagnostic on the main file.
- Possible improvements, none needed for M1:
  - let DC005 run on VIVA+-style decks: a list of unknown keywords known not to refer to MAT, SECTION or HOURGLASS;
  - overflow detection, once the field reader reads every field of a card (M4).
