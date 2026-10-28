# M0 assessment: can deckcheck stand on dynars?

Date: 2026-10-28 · dynars 1.1.0 · LS-DYNA R16.1 Student as referee
Evidence: `bakeoff/findings.md`, `bakeoff/triage.md`, `bakeoff/results/*.jsonl`.

## Verdict: NO-GO for option A as specified

dynars' **parser and editor are mostly sound, with two parser-level defects**: it drops a `*PART` whose title card
is blank, and it does not index `*PART_INERTIA` as a part. Its **reference rules and include resolution are
not sound**. They produced 68 errors on the official LS-DYNA decks and VIVA+, and 62 of them are false:
- 43 false by LS-DYNA's input phase;
- 16 false because the files exist and LS-DYNA honours `*INCLUDE_PATH`;
- 3 false by reading the field.

The other 6 errors were real.

On VIVA+, the deck the spec names as decisive, dynars loaded 2 of the model's 18 files, because it ignores
`*INCLUDE_PATH`. Spec section 7 says a failure on VIVA+ or the vehicle model sends the decision back to Chintan.
Option A, "dynars' rules plus a thin layer", is therefore not supported. Building on dynars' parser remains
supported, with the two defects as known work.

## The five criteria, as measured

| # | Criterion (spec §7) | Result | Evidence |
|---|---|---|---|
| 1 | Parses every deck without crashing, within the memory cap | **Pass, with a caveat.** 35/35 official decks, 15/15 torture decks, VIVA+ and the Yaris parsed, no crash. Peak 182 MB on tier 1 (cap 4 GB), 961 MB on the 1.5-million-element Yaris (cap 2 GB). Caveat: on VIVA+ "parsed" means 2 of 18 files. | `corpus_tier1.jsonl`, `corpus_tier2.jsonl` |
| 2 | Zero unexplained findings | **Fail.** See the table below: every reference error and every VIVA+ include error was false. | `triage.md` |
| 3 | Finding lines point at the right keyword block | **Partial.** `unreferenced_entities` 106/106 correct, `duplicate_ids` correct on torture decks, `references_resolve` 33/46, `include_missing` 0/22 (always line 0). All 13 `references_resolve` misses land on a `$#` ruler comment line (keyword + 1 in 10 of them), never on a data card: dynars counts comment lines as cards. Line numbers are identical across LF, CRLF and Latin-1 (torture `crlf_seeded`, `latin1_seeded`). Note `line_ok` only checks that the line starts with the keyword, so it cannot catch a finding that points at the wrong block of the same keyword. | `triage.md` |
| 4 | `set_field` round-trip | **Pass, with a caveat.** Writing back unchanged is byte-identical on 83/83 tier-1 files, 2/2 VIVA+, 4/4 Yaris and every torture case (CRLF and Latin-1 included). A one-field edit stays in place and changes 1 line on 30 of the 31 tier-1 decks with a `*PART`, and on the Yaris. It fails on the 31st (`set_field` returns `None`) because that part's title card is blank and dynars drops the part. Changed lines, not changed bytes, were measured. | `corpus_tier1.jsonl`, torture `blank_title` |
| 5 | Long format, free format, `*PARAMETER` | **Partial.** Free format, `*PARAMETER`, lowercase keywords, comments, CRLF and Latin-1 all handled. The long-format `+` suffix is not: the material is lost and a false error follows. | `findings.md` |

## Rule accuracy

| Rule | Decks | Errors / warnings | Real | False | Unclassified |
|---|---|---|---|---|---|
| references_resolve | tier 1 | 46 errors | 0 | 46 | 0 |
| include_missing | tier 1 | 6 errors | 6 | 0 | 0 |
| include_missing | VIVA+ | 16 errors | 0 | 16 | 0 |
| unreferenced_entities | tier 1 | 106 warnings | — | ≥ 5 | 101 |
| all error rules | Yaris (CCSA) | 0 errors | — | — | — |
| unreferenced_entities | Yaris (CCSA) | 13 warnings | 0 | 9 | 4 |
| duplicate_ids | all | 0 on real decks; 2/2 seeded caught | — | — | — |

The false alarms are systematic, not random. Seven defects explain all of them; the last two are in the parser itself:

1. **`*INCLUDE_PATH` ignored**: 16 VIVA+ errors, the torture `include_path` case, and an unloaded model.
2. **`_ID` keyword option**: the extra leading ID card is read as the first data card. 26 reference errors, and it
   hides references, which feeds false "unused" warnings.
3. **ICFD/mesh id namespace**: ICFD part ids are checked against structural `*PART`. 13 errors.
4. **Wrong field type or misread field**: a rigid part read as a node; `arcctl = 0` reported as Node 1;
   contact set type ignored. 5 errors.
5. **References dynars does not follow**: `*DEFINE_TABLE` → curves; sign-encoded ids (a negative CN meaning load
   curve |CN|); and, on the Yaris, `*INCLUDE_TRANSFORM` tranid, `*RIGIDWALL_PLANAR` nsid and
   `*INITIAL_VELOCITY_GENERATION` set ids. These produce false "unused" warnings: 9 of 13 on the Yaris.
6. **`*PART_INERTIA` not indexed as a part**: 2 reference errors in EX09 (a part set and a rigid-body constraint
   pointing at Part 1). With no ordinary `*PART` in a deck, dynars skips part checks entirely, so the defect only
   shows when both kinds are present (torture `part_inertia`, pinned as strict xfail).
7. **A `*PART` with a blank title card is dropped**: the part disappears, its fields read as `None`, `set_field`
   fails, and its material and section are reported unused. Pre-processors often export blank titles (tutorial 6;
   torture `blank_title`, pinned as strict xfail).

The Yaris is the counterweight: on a 1.5-million-element crash vehicle, dynars resolved `*INCLUDE_TRANSFORM`,
raised no false errors, round-tripped all 4 files and edited in place, at a 953 MB peak. Its error rules are not
wrong everywhere. They are wrong on specific keyword families, and VIVA+ and the ICFD/implicit examples hit them.

Plus the long-format `+` suffix (criterion 5) and the line-0 include findings (criterion 3).

## What the bake-off also established

- LS-DYNA itself misreads tab-separated cards. A material vanished, and the run ended "MATERIAL ID 1 does not
  exist". That is a real check for deckcheck (DC003) that no tool here provides.
- LS-DYNA's input phase ("initialization completed") is a workable referee for reference checks, and costs
  seconds per deck.
- The official implicit examples include `INCLUDE_FILES/…`, which only resolves from the parent folder. dynars
  was right about those 6, and LS-DYNA agrees.

## Routes forward (Chintan's decision)

| Route | What it is | For | Against |
|---|---|---|---|
| B1. dynars parser + deckcheck's own reference layer | Use dynars for parsing and edits. deckcheck resolves includes (`*INCLUDE_PATH` included), keeps its own positions (dynars counts `$#` lines as cards), and checks references itself, from dynars' keyword data plus our own schema for `_ID`, ICFD and the misread fields. It must also work around the two parser defects (blank-title `*PART`, `*PART_INERTIA`). | Keeps what works; the seven defects become deckcheck's test cases; we control false alarms | M1 grows back to the original ~2 weeks or a little more. Two of the seven defects are in the parser, so more may surface. It still depends on a dormant single-maintainer parser |
| B2. Fix dynars upstream | Contribute fixes for the seven defects to dynars (MIT), each with its reproducing deck from this corpus | Best open-source citizenship; deckcheck stays thin | Depends on a maintainer silent since 2026-08-15; our schedule becomes theirs |
| B3. pydyna as parser | Swap to Ansys' pydyna | Backed by Ansys | Unmeasured; heavy dependencies (Docker, DPF); positions and round-trip unknown. Would need its own M0 |

Recommendation: **B1, offering B2's fixes upstream as a side effect.** The corpus and the LS-DYNA referee built in
M0 are exactly the test harness a reference layer needs. Every defect above is a ready-made failing test. Upstream
fixes cost little once our layer has them, and they don't block us. The case for B1 weakens if the parser-level
count grows: if M1 finds a third parser defect, measuring pydyna (B3) becomes worth its own short M0.

## Still open

- 105 `unreferenced_entities` warnings are unclassified (101 tier 1, 4 Yaris; no referee for "unused"). Of the 14
  classified across tier 1 and the Yaris, all 14 were false. DC005 cannot be trusted as dynars reports it.
- M0 artefacts that are machine-specific: tier-1 decks are read from the local LS-DYNA install, the Yaris is a
  local download, and the referee needs LS-DYNA Student. CI can run only the torture tier and VIVA+.
- The Yaris could not be put to LS-DYNA: the Student version's model-size limit is far below 1.5 million elements.
  Its 0 errors are dynars' own result, not refereed.
- Reproduce: `python -m bakeoff.run --torture --out bakeoff/results/torture.jsonl`, then
  `--corpus --tier 1 --out …/corpus_tier1.jsonl`, then `--corpus --tier 2 --cap-mb 2048 --out …/corpus_tier2.jsonl`.
  `tier1_input_oracle.py` has machine-specific paths.
