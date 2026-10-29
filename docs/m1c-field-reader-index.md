# M1c report: field reader and index

Date: 2026-10-29 · referee LS-DYNA R16.1 Student · evidence in `bakeoff/results/m1c_referee.txt`,
`bakeoff/results/m1c_probes.json` and `bakeoff/results/m1c_index.jsonl` · plan
`docs/plans/2026-10-29-m1c-field-reader-index.md`

## Verdict

- `deckcheck.fields` reads every field of every block deckcheck has data for, in LS-DYNA's order, with exact line
  and column span. Where it can't decide (an undecidable condition, a layout that doesn't match the deck), it stops
  and says so (`unread`) instead of guessing.
- `deckcheck.index` collects each entity kind's definitions and references across the include tree, with
  `*INCLUDE_TRANSFORM` offsets, sign rules, `*PARAMETER` values, and an "uncertain" mark wherever it can't see all
  of a kind.
- **The corpus gate passes.** Across 35 tier-1 decks, VIVA+ (18 files) and the Yaris (4 files), the only findings are:
  - 632 dangling `PART 1` references in `tutorial/2.Tensile_test/tensile_test.k`. That file is a mesh with no
    `*PART`, and LS-DYNA rejects it for that reason, so the findings are real.
  - One `unread` stop on a keyword whose pydyna layout is from another version. The stop is deliberate.
- **Memory.** Yaris peak about 1,150 MB under the 2,048 MB cap, in about 60 s. M1b's reader alone took 683 MB.
- **LS-DYNA settled 27 new torture cases and 10 offset probes.** Taking the M1b cases with them, every rule the reader applies
  traces to an LS-DYNA verdict or to pydyna's own reader code.

## 1. What LS-DYNA decided

19 cases from the plan (Task 1), 8 more that the corpus raised (Task 7), and offset probes for 10 kinds. Deciding
lines are from the full `messag`/`d3hsp` logs.

| Case | Question | LS-DYNA | Deciding line | Rule adopted |
|---|---|---|---|---|
| table_dangling, table_ids, table_before | Is `*DEFINE_TABLE`'s curve column an id? | dangling accepted; curves *before* the table rejected even with matching ids | Error 20308 `Table ID= 10 has an invalid load curve ID specified` | No: the table takes the curves that follow it, by position. `lcid` carries no link. |
| contact_type2_bad / _none | sstyp 2: part set? | missing set 1 with part 1 accepted; neither set nor part 99 rejected | Error 10144 `part set for contact interface # 99 is not found` | A part-set reference falls back to the part with that id (`LOOKUP["SET_PART"]`) |
| velocity_styp1_bad / _none | styp 1: part set? | same pattern | Error 10144 `part set for initial velocity # 99` | same fallback |
| contact_type3_bad | sstyp 3: part? | rejected | Error 20216 `part # 99 is out-of-range` | type map confirmed |
| contact_type4_bad | sstyp 4: node set? | rejected | Error 10144 `node set for contact interface # 1 is not found` | type map confirmed (nodes-to-surface: a single-surface contact can't take a node set, Error 11089) |
| velocity_styp3_bad | styp 3: node set? | rejected | Error 10144 `node set for initial velocity generation # 1` | type map confirmed |
| spc_set_none | Does `*BOUNDARY_SPC_SET` check its node set? | accepted, no warning | — | `nsid` is a use, never dangling (`set.when = "unchecked"`) |
| inc_path_in_include | Does `*INCLUDE_PATH` inside an include apply? | accepted | — | resolver already agreed |
| inc_blank_in_continuation | Does a blank card end a ` +` name? | rejected | Error 10087 `File sub\ does not exist` | yes; resolver already agreed |
| inc_empty | `*INCLUDE` with no filename | accepted | — | resolver already agreed |
| (probe) inc_absolute | Absolute include name | accepted | — | resolver already agreed (`includes.py` `_locate`) |
| long_keyword | `*KEYWORD LONG=Y` makes cards 20 wide? | accepted | — | `LONG=Y` only. `LONG=S` is the standard format: the first probe used it and failed, Error 10246. |
| long_section | 8-field `+` card on one 160-column line | accepted | — | one line per card |
| parameter_ref | `&name` in an id field | accepted | — | substituted |
| spc_set_id | `_ID` card before the main card (M0 defect) | accepted | — | pre/2 ordering |
| zero_ref | 0 is no reference (M0 defect) | accepted | — | 0 and blank are no reference |
| repeat_velocity, repeat_history_id, repeat_load_node_set | Is a second instance under one keyword read? | all rejected for the second instance's missing target | e.g. Error 20211 `undefined node # 99` | Cards left after the layout start another instance (`REPEAT_INSTANCES`) |
| repeat_mat | Is a second `*MAT_ELASTIC` line material 2? | accepted (the part uses material 2) | — | same rule, for materials too |
| nodal_rigid_part / _none | Does a nodal rigid body's `pid` define a part? | accepted / rejected | Error 20368 `must be defined as rigid` | definer row `CONSTRAINED_NODAL_RIGID_BODY.pid → PART` |
| set_general_rows | Is a second `*SET_NODE_GENERAL` row read? | rejected for its part 99 | Error 10147 `part 99 to be added to node set is not defined` | `SET_*_GENERAL` option rows repeat; `PART` rows link to parts |
| set_part_alias | Is `*SET_PART` (no `_LIST`) a part list? | accepted | — | alias `SET_PART → SET_PART_LIST` (pydyna has no `SET_PART`) |

**`*INCLUDE_TRANSFORM` offsets.** Each probe ran a control (all offsets 0) that had to pass and a negative control
(an id no offset produces) that had to fail.

| Kind | Field | | Kind | Field |
|---|---|---|---|---|
| MAT | idmoff | | PART | idpoff |
| SECTION | **idroff** | | SET_PART, SET_NODE, SET_SEGMENT | idsoff |
| HOURGLASS | **idroff** | | ELEMENT_SHELL | ideoff |
| NODE | idnoff | | DEFINE_CURVE | idfoff |

Kinds not probed are uncertain under a nonzero transform. The Yaris's wall include needed exactly these, so its
index is fully certain.

Two probes were broken and were fixed before they counted:
- `*BOUNDARY_SPC_SET` accepted every offset: LS-DYNA doesn't check that reference.
- A single-surface contact rejects node sets for a reason of its own.

The negative control now catches the first kind of break.

## 2. Extraction v2

- **Conditions.** 275 card conditions and 30 bounded lengths, extracted as pydyna source text, with zero
  ambiguous lambdas. pydyna's library default (`len(self.table)`) means "unbounded", and 110 such lengths were
  recognised as that.
- **The evaluator** is a whitelisted `ast` walk with no `eval` and no pydyna at runtime. It refuses 9 texts: they
  read other cards' state or a pandas frame. A card with one of these conditions:
  - is read when present, if the text is pydyna's "has values" chain;
  - otherwise stops the block as `unread`.
- **Per row.** `self.elements['n5'].any()` is evaluated per row: LS-DYNA reads element by element.
- **Legacy layouts.** Extraction also records pydyna's legacy layouts (`ELEMENT_SOLID`, `ELEMENT_SOLID_ORTHO`). The
  field reader picks one when the first card is longer than 16 characters, pydyna's own test (`before_read`).

## 3. Corpus

| Deck set | Files | Definitions | References | Dangling (real) | Duplicates | Problems | Uncertain kinds | Peak MB | Slowest |
|---|---|---|---|---|---|---|---|---|---|
| Tier 1 (35 decks) | 1–4 each | 2,245,114 | 3,559,910 | 632, one deck (tensile_test) | 0 | 1 `unread` (PSD fatigue) | uses only, on 4 decks (unmapped contact types, unread PSD card); no definitions | 194 | 8.7 s (EX04) |
| VIVA+ | 18 | 1,350,217 | 1,271,764 | 0 | 0 | 0 | uses only: `SET_SOLID` (`&Solid_e_o` is a `*PARAMETER_EXPRESSION`), `DEFINE_CURVE` (a table), `PART`, `SET_PART`, `SET_NODE` (unmapped contact types) | 548 | 20 s |
| Yaris | 4 | 3,012,957 | 6,314,548 | 0 | 0 | 0 | uses only: `DEFINE_TRANSFORMATION` (`tranid` not read), `PART` (unmapped contact types); no definitions | 1,150 | 58–64 s |

Judged-real findings are pinned in `tests/corpus/expected_index.toml` and tested by `tests/test_index_corpus.py`
(tier 1).

**What the corpus forced.** The first run found systemic misreads, not one-off quirks. Each fix has a test and
cites its evidence:

| Finding on the first run | Mechanism | Fix |
|---|---|---|
| 72,921 of 145,837 solids defined in EX01 (every second line) | pydyna's two-card `ELEMENT_SOLID`; the deck uses the one-line legacy format | legacy layout, chosen by pydyna's own rule |
| `extra` cards in 20 keywords (`BOUNDARY_PRESCRIBED_MOTION_*`, `LOAD_NODE_SET`, `INITIAL_*`, ...) | LS-DYNA repeats a keyword's card group; pydyna models one instance | `REPEAT_INSTANCES`, refereed by four cases |
| `extra` in `SET_SOLID`, `SET_*_GENERAL`, `CONSTRAINED_INTERPOLATION`, `DEFINE_FRICTION` | a list card that pydyna models as one card | `set.rows` overrides |
| `unread` in `CONTROL_SHELL`, `DATABASE_BINARY_*`, `CONTROL_TIMESTEP` (SET_PART/DEFINE_CURVE uses uncertain on 30 of 35 decks) | pydyna's "has values" chains are a writer test | read when a card remains; pydyna's reader reads first, then decides |
| `unread` on `*_MPP` contacts, `CONTROL_IMPLICIT_EIGENVALUE` | conditions on the card's own fields (`mpp2` is a `&` flag) | read the card, then decide, as pydyna does |
| VIVA+ thickness cards read as elements, after the repeat rule | `ELEMENT_SHELL_THICKNESS_BETA` and 6 siblings lack the `n5` condition their siblings have | `set.active` override |
| `PART 1` dangling in two implicit benchmarks | part defined by `*CONSTRAINED_NODAL_RIGID_BODY` | definer row, refereed |
| `ldpsd2 = 1000000` dangling (PSD fatigue) | pydyna's layout is another version of the keyword | `set.stop`: deckcheck stops there |
| `ICFD_PART` duplicate (main_fsi) | `*ICFD_PART_VOL` ids are their own namespace | separate kind, looked up together |
| `SET_PART` / `PART` uncertain on VIVA+ | `*SET_PART_TITLE` unresolved; `*PART_AVERAGED` defines parts | alias (refereed), definer row |
| Yaris `ELEMENT_SHELL`, `SET_SEGMENT` uncertain | offsets not probed | two more probes |

## 4. Spec §11 progress

| M0 defect | Test |
|---|---|
| `include_path` | `test_torture_index[include_path]`, `test_includes` |
| `long_format` | `test_torture_index[long_format]`, `test_long_format_suffix`, `long_keyword`, `long_section` |
| `blank_title` | `test_torture_index[blank_title]`, `test_part_table_group_with_blank_heading` |
| `part_inertia` | `test_torture_index[part_inertia]`, `test_core_definers` |
| an `_ID` case | `test_torture_index[spc_set_id]`, `test_id_option_card_comes_first` |
| an ICFD case | `test_icfd_parts_are_their_own_namespace` (main_fsi) |
| a misread field | `test_torture_index[zero_ref]`, `test_zero_and_blank_are_no_reference`, `table_dangling` |

Exact line and span: every rejected torture case carries an `[index]` table written by hand from LS-DYNA's words,
and `test_torture_index` compares the index against it on all 55 cases.

## 5. Final review fixes

A fresh reviewer found false alarms and crashes that the corpus didn't trigger. Each is fixed, with a test that failed first:
- **Legacy solids in long and free format** (false duplicates). pydyna's 16-character test only holds for fixed 8-wide
  cards, so the block now stops as `unread`.
- **`LONG=Y` with `*INCLUDE_TRANSFORM`** (offsets read 10 wide). The index is blind there.
- **A `*PARAMETER` of the wrong type in an id field**, or a non-integer id. These are now `UNKNOWN` and uncertain,
  where before the definition was dropped.
- **Crashes on huge or non-finite values** (`1e400`, `nan`, a 20-digit id):
  - such values are `bad`, or uncertain when out of range;
  - lengths that aren't counts stop the block;
  - arithmetic in conditions is numbers only.
- **Python-lenient numbers** (`1_0`) are now `bad`.
- **A repeated instance that runs out of cards early** is reported (`unread`), the signal of a too-short layout. It
  never fires on the corpus.
- **The part-set fallback when part and set offsets differ** is a use, never checked, because it isn't refereed.
- **Columns past 65535** are reported at 65535.

One reviewer question went to LS-DYNA: is a `*DEFINE_FUNCTION` id accepted where a curve is linked
(`*LOAD_BODY_Z`)? No: Error 10141 `Load curve id 5 is undefined`. So deckcheck's dangling finding there is right.

## 6. What this means for M1d

- **DC001** reports `Index.dangling()`. It is already silent on uncertain kinds and blind trees. When the tree has
  missing includes (`Tree.problems`), it should say the target may live in the missing file.
- **DC002** reports `Index.duplicates()`.
- **DC003's inputs** are `bad` problems (a value not of its field's type, tabs), `extra` (now rare: only when an
  instance reads no cards) and `unread` (an info line, not a warning).
- **DC005 can't take `uncertain_uses` as the whole story** (final review, I1). `uncertain_uses` marks the uses
  deckcheck knows it can't place:
  - unread blocks and unknown values;
  - type values the data doesn't map;
  - curves taken by a `*DEFINE_TABLE`;
  - `*INCLUDE_TRANSFORM` `tranid`.

  A field pydyna's data doesn't mark as a reference at all (for example `*BOUNDARY_PRESCRIBED_MOTION_NODE` `lcid`)
  is invisible, so `Index.used(kind)` is a lower bound. M1d needs a per-kind basis before DC005 reports a kind, such
  as an audit that every field referring to it is linked. MAT, SECTION and HOURGLASS, referred to almost only from
  `*PART`, are the likely first candidates. `used()` includes possible uses (negative ids, unchecked references,
  fallbacks under differing offsets).
- **Open reading rules:**
  - nested transforms (an ancestor's offsets as well as the file's own) are not refereed, so they make kinds
    uncertain;
  - long-format series stop;
  - kinds not probed for offsets are uncertain under a transform.
- **Decided (Chintan, 2026-10-29): M1d warns on references LS-DYNA accepts but ignores.** LS-DYNA leaves some
  references unchecked (`*BOUNDARY_SPC_SET` node set). The index keeps treating them as uses, so they never appear as
  dangling. M1d adds a separate warning for them: "LS-DYNA accepts this, but the boundary condition does nothing".
  The principle is to give the engineer every fact and let them decide what to do with it.
