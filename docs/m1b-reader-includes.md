# M1b report: reader and include resolver

Date: 2026-10-28 · referee LS-DYNA R16.1 Student · evidence in `bakeoff/results/m1b_referee.txt` and
`bakeoff/results/m1b_reader.jsonl`

## Verdict

- `deckcheck.reader` splits a file into keyword blocks and cards with exact line numbers. It keeps blank cards, and
  columns are byte offsets.
- `deckcheck.includes` follows includes the way LS-DYNA does, as decided by LS-DYNA itself on 13 new torture
  decks.
- VIVA+ loads all 18 files (M0's dynars: 2 of 18). The Yaris loads its 4 files, with the wall's transform offsets,
  at 683 MB peak in 4.8 s. Every deck runs under the 2 GB cap, with no crash.
- The only problems found on the real corpus are 6 missing includes in three LS-DYNA examples. LS-DYNA rejects
  those decks for the same reason, so they are real findings.

## 1. What LS-DYNA decided

Each case pairs a "good" file (defines material 1, which the part needs) with a "bad" one (material 2 only), so
LS-DYNA's verdict shows which file it read. The deciding lines are from the full `messag` logs.

| Case | Question | LS-DYNA | Deciding line | Rule adopted |
|---|---|---|---|---|
| inc_nested_sibling | Is a nested include searched in the including file's folder? | rejected | Error 10087 `File b.k does not exist` (it exists beside `sub/a.k`) | `SEARCH_INCLUDING_DIR = False` |
| inc_nested_main | Is it searched in the main deck's folder? | accepted | — | `SEARCH_MAIN_DIR = True` |
| inc_nested_both | Both folders hold it: which wins? | rejected | `Open include file: b.k`, `MAT 1 is not found` | main folder (`INCLUDING_DIR_FIRST = False`, moot) |
| inc_path_precedence | Does an `*INCLUDE_PATH` folder beat the main folder? | rejected | `Open include file: mat.k`, `MAT 1 is not found` | `PATH_BEFORE_DIRS = False`: main folder first |
| inc_path_relative | Is `*INCLUDE_PATH_RELATIVE` relative to its own file or to the main deck? | rejected | `Open include file: .\lib\mat.k`, `MAT 1 is not found` | `PATH_RELATIVE_TO_FILE = False`: relative to the main deck |
| inc_path_backslash | VIVA+'s `.\lib\` form (backslashes, trailing separator) | accepted | — | backslashes normalised |
| inc_path_late | Does a path apply to an include written before it? | rejected | Error 10087 `File mat.k does not exist` | `PATH_APPLIES_EARLIER = False` |
| inc_multi | Several filename cards on one `*INCLUDE`? | accepted | — | `MULTI_FILENAME = True` |
| inc_continuation | Does a name ending in ` +` continue on the next card? | accepted | — | `CONTINUATION = True` |
| inc_cycle | a.k → b.k → a.k | rejected | Error 10088 `in *INCLUDE file is already opened ... check nesting of files` | reported as a `cycle` problem |
| inc_transform | `*INCLUDE_TRANSFORM` laid out like the Yaris, blank cards included | accepted | — | offsets read by field name |
| end_main | Is text after `*END` ignored? | accepted | — | `STOP_AT_END = True` (reader) |
| end_include | Does `*END` in an include end only that file? | accepted | — | same rule, per file |

Two observations for later:
- LS-DYNA reports a missing include twice, and in `inc_path_late` it opens `lib\mat.k` after reporting
  it missing: it reads includes in two passes. Its error stands either way, so deckcheck reports the miss as LS-DYNA
  does.
- In short: a relative include name is tried against the main deck's folder first, then each `*INCLUDE_PATH`
  folder in the order it appeared. Both `*INCLUDE_PATH` and `*INCLUDE_PATH_RELATIVE` folders are relative to the
  main deck. The including file's own folder is never searched.

## 2. Corpus

| Tier | Decks | Files | Blocks | Cards | Problems | Peak MB | Slowest deck |
|---|---|---|---|---|---|---|---|
| Torture | 28 | 45 | 264 | 374 | 5 missing, 1 cycle (all expected) | 52 | 0.1 s |
| Tier 1 | 35 | 83 | 1,843 | 2,806,010 | 6 missing (real, below) | 134 | 0.5 s |
| VIVA+ | 1 | 18 | 3,669 | 1,452,003 | 0 | 362 | 1.9 s |
| Yaris | 1 | 4 | 4,765 | 3,023,165 | 0 | 683 | 4.8 s |

- Yaris `wall.key` carries offsets `idnoff` … `idroff` = 10,000,000 each, matching `combine.key:91-97`.
- Every torture deck's files and problems match its `[resolver]` table.
- No deck uses an include form deckcheck does not follow (`unfollowed`: 0).

**The 6 tier-1 problems, judged.** `bolts001`, `eigen001` and `doorstiff001` each include
`INCLUDE_FILES/control_cards_*.key` and `INCLUDE_FILES/database_cards_static.key`. `INCLUDE_FILES/` is a sibling of
`EXAMPLES/`, not inside it. M0's referee run (`tier1_lsdyna_input.jsonl`) has LS-DYNA rejecting all three decks with
Error 10087 when run from the deck's folder, and accepting bolts001 when run from `guidelines/implicit`. These are
real findings and become expected DC004 findings in M1c.

## 3. Spec §11 progress

The seven M0 defects:

| M0 defect | Status |
|---|---|
| `*INCLUDE_PATH` ignored (VIVA+ 2/18 files) | **fixed**: 18/18; torture `include_path`, `inc_path_*` |
| Blank title card dropped | **fixed** at the reader: `test_blank_title_is_a_card` |
| Missing include reported at line 0; `\\?\` path prefix | **fixed**: filename card line and column span; plain paths (`test_tree_paths_are_plain`) |
| Long format | `+` suffix recorded per block; field widths are M1c |
| `_ID` card misread, ICFD namespace, misread field, `*PART_INERTIA` not indexed | M1c (field reader and index) |

## 4. What this means for M1c

1. **`*PARAMETER` substitution moved to the field reader**, because it needs field positions. The reader keeps
   `*PARAMETER` blocks as ordinary blocks.
2. **Long format beyond the `+` suffix** (`*KEYWORD LONG=`) is not handled and appears nowhere in the corpus. The
   reader keeps the `*KEYWORD` line as a block, so its cards are available. A long-format `*INCLUDE_TRANSFORM +`
   gets an `unread` problem and zero offsets, never silently misread offsets.
3. **Nested transforms are not composed.** Each `FileNode` holds its own offsets. Composing them along `parent` needs
   an LS-DYNA case first.
4. **Which offset applies to which kind** (`idnoff` → nodes, `idpoff` → parts, …) still needs evidence before the
   index uses it.
5. **`unfollowed` includes** (binary, auto-offset, …) hide ids. DC001 must treat target kinds as not fully covered
   when any appear. `*INCLUDE_AUTO_OFFSET` is wider still: it changes how every *later* include offsets its ids, so
   all ids after it are unreliable, not just one file's. None appear in the corpus.
6. **Working directory.** LS-DYNA resolves relative names against its working directory. deckcheck assumes that is
   the main deck's folder, which is what a user normally does and what the three tier-1 rejections confirm. A CLI
   option for a different run folder can come later if users ask.
7. **Memory.** Cards are one `NamedTuple` per line: the Yaris needs 683 MB for 3 million cards. M1c's index adds to
   this, so the cap stays a gate on the corpus run.
8. **Not yet refereed, so the resolver's behaviour there is a guess to confirm before M1c relies on it:** an
   `*INCLUDE_PATH` inside an included file (applied globally to later includes, relative to the main deck); a blank
   card inside a ` +` continuation (ends the name); trailing text after a filename (part of the name); absolute
   include names; an `*INCLUDE` with no filename card (silently nothing). Proposed cases: `inc_path_in_include`,
   `inc_blank_in_continuation`, `inc_absolute`, `inc_empty`.
