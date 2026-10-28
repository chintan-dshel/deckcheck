# M1a report: keyword data from pydyna

Date: 2026-10-28 · ansys-dyna-core 0.12.1 (MIT) · evidence in `bakeoff/results/`

## Verdict

pydyna's field database is usable as deckcheck's keyword data. It is extracted into
`src/deckcheck/data/keywords.json` (4.97 MB, no runtime dependency) and corrected by 17 evidence-backed overrides.
It is accurate where M0's dynars failed (`_ID` card placement, `*PART_INERTIA`, `*PART` heading,
`*INCLUDE_TRANSFORM`, `*RIGIDWALL_PLANAR`).

It has three systematic gaps that M1b and M1c must design for:
- it says which fields **reference** a kind, but never which keyword **defines** one;
- contact surfaces and other type-dependent references carry no link;
- 275 cards (247 top-level, 28 inside card sets and table groups) are conditional on field values.

## 1. The data

| Measure | Value |
|---|---|
| Keywords | 3,171 (no name collisions; extraction deterministic) |
| Cards (top level) | 12,750: 12,642 plain, 58 tables, 24 series, 13 table groups, 9 card sets (with their cards inside: `SECTION_*`, `HOURGLASS`, `INITIAL_STRESS/STRAIN_SHELL`, `MAT_295`), 2 text, 2 include |
| Conditional cards | 275 (247 top-level) |
| Keywords with option cards (`_ID`, `_TITLE`, `MPP`, `A`–`G` …) | 1,327 |
| `X_ID` keywords pydyna models as a separate class, not an option | 119 (90 `AIRBAG_*`, 15 `DATABASE_*`, 7 `LOAD_*`, …) |
| Reference fields (links) | 7,993 in 1,865 keywords, 20 target kinds: DEFINE_CURVE 3,178 · NODE 2,229 · SET_PART 507 · PART 478 · SET_NODE 277 · … |
| File size | 4.97 MB JSON, shipped uncompressed (threshold 10 MB) |

## 2. Coverage of the M0 corpus

| Tier | Keyword lines resolved |
|---|---|
| Torture (15 decks) | 110 / 137 |
| Tier 1 (35 official decks) | 1,805 / 1,926 |
| VIVA+ | 24 / 27 (lower bound: the coverage scan does not follow `*INCLUDE_PATH`; M1b's resolver will) |
| Yaris | 4,762 / 4,769 |
| **All** | **6,701 / 6,859 (97.7 %)** |

Every unresolved line but one is structural and absent by design: `*END` (104), `*TITLE` (51) and
`*KEYWORD_ID`/`_JOBID` (2). The reader handles these directly. The exception is `*TERMINATION_NODE` (1), which is
absent from pydyna entirely and passes through unchecked.

Getting there:
- The extractor first dropped the cards inside pydyna's card sets, which left `SECTION_*` and `HOURGLASS` with no
  fields; it now extracts them, which also brought `SECTION_SOLID_TITLE`.
- `resolve()` honours the `_ID`/`_TITLE` options added by overrides (joints, `ICFD_MAT`, `CONTACT_2D_…`,
  `LOAD_SEGMENT_SET_NONUNIFORM`).

**This is corpus coverage, not data coverage.** Outside the corpus pydyna still omits some `_ID`/`_TITLE` options
(e.g. on `LOAD_NODE_SET`, `LOAD_SEGMENT_*` and `DAMPING_*` variants). Such a keyword line does not resolve, so it
passes through unchecked: safe by spec §4, but the entities it defines become invisible. M1c must therefore treat
an unresolved keyword that looks like a definer as "unknown", so references into it do not become false
dangling-reference errors.

## 3. The 16-case check

| Keyword | Data says | Deck says | Verdict |
|---|---|---|---|
| BOUNDARY_SPC_SET | `ID` option `pre/2` (before the main card); nsid → SET_NODE | bolts001.key:78-81: id/heading card, then nsid card | correct |
| CONTACT_DRAWBEAD | `ID` pre; lcidrf/lcidnf → DEFINE_CURVE; surfa/surfb no link | cross_member_op10.dyn: curves used; set kind per surfatyp | override (surfa/surfb by type) |
| CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR | surfa/surfb no link | bolts001.key:291: surfa 6, surfatyp 2 = part set 6 | override (by type) |
| CONTACT_AUTOMATIC_SINGLE_SURFACE | pydyna names the fields ssid/msid/sstyp/mstyp; no link | same layout as above | override (ssid/msid by type; this keyword only) |
| CONTACT_AUTOMATIC_NODES_TO_SURFACE | surfa/surfb no link | kind per surfatyp/surfbtyp | override (by type) |
| ICFD_PART | table pid/secid/mid; no links, no ICFD kind | mesh_fluid.k:7-21 defines ICFD parts 1-5 | override (defines ICFD_PART) |
| ICFD_PART_VOL | pid card + spid table; no links | fluid_main.k:86-90 | override (defines; spid → ICFD_PART) |
| MESH_VOLUME | volid + int series; no links | fluid_main.k:99-103: series = ICFD part ids | override (→ ICFD_PART) |
| PART_INERTIA | title card, then pid card …; mid → MAT | torture `part_inertia` | correct (defining is §4's gap) |
| PART | table group: heading then ids | torture `blank_title` | correct: a blank heading is the reader's job (keep blank lines) |
| BOUNDARY_PRESCRIBED_MOTION_RIGID | lrb → PART; pid unlinked | BARRIER_DELAY_20MS.k:38221 pid 19 = *PART at 38600 | override (pid → PART) |
| CONTROL_IMPLICIT_SOLUTION | arcctl → NODE | beam_sub.key:66 arcctl = 0 | correct, provided 0/blank means "no reference" (M1c rule) |
| DEFINE_TABLE | one 20-wide float series | crashbox.k:153342-153344: value (20) + curve id (10) per row | override (row = value + lcid → DEFINE_CURVE) |
| AIRBAG_SIMPLE_PRESSURE_VOLUME(_ID) | lcid, lciddr → curve; cn unlinked; `_ID` is a separate class | BARRIER_DELAY_20MS.k:38191-38197 (`_ID` variant) cn = -1, curve 1 defined | override on both keys (negative cn → curve) |
| INCLUDE_TRANSFORM | tranid → DEFINE_TRANSFORMATION | Yaris combine.key:101 | correct |
| RIGIDWALL_PLANAR | nsid, nsidex → SET_NODE | Yaris combine.key:238 | correct |
| INITIAL_VELOCITY_GENERATION | id unlinked | Yaris set-yaris:224-236: styp 1 → part set, styp 3 → node set | override (by type) |

The type-dependent maps come from the corpus, not from memory of the manual (`bakeoff/type_field_evidence.py`).
For each use, the id is matched against every definition in its deck, and only ids matching exactly one kind
count:
- contact type 2 → SET_PART (4), 3 → PART (7), 4 → SET_NODE (9);
- velocity styp 1 → SET_PART (3), 3 → SET_NODE (1).

Contact type 0 had one contradictory case and stays unmapped: those references go unchecked rather than risk
false alarms.

Caveat on the method: "matches exactly one kind" is evidence only if the scan sees all of a deck's definitions.
The scan does not follow `*INCLUDE_PATH`, reads 10-wide fields only (long-format ids are misread), and an id can
coincide with a definition of another kind, which is how type 0 got its contradictory case. The maps are therefore
limited to type values with several unique matches and no contradicting one. The M1c referee runs (LS-DYNA on
seeded decks) should confirm each mapped value.

## 4. What this means for M1b and M1c

1. **No "defines" data.** pydyna marks the referring side only. M1c needs a definer table: which keyword families
   define which of the 20 kinds, and through which id field (`*PART`/`*PART_INERTIA`/… → PART via pid; `*MAT_*` →
   MAT via mid; `*SET_PART*` → SET_PART via sid; `*DEFINE_CURVE*` → DEFINE_CURVE via lcid …). It must be built and
   checked against the corpus the same way as section 3: an M1c task, not a guess.
2. **Conditional cards (275).** pydyna decides them with Python lambdas over field values. Roughly half compare
   a field (`self.n > 0`, `abs(self.dof) in [9, 10, 11] or self.vad == 4`), most of the rest test truthiness
   (`self.mpp2`, `self.pr and self.pr < 0`), and a few (~14) test whether a previous card has values. These shares
   are approximate, from an ad hoc scan of the lambda sources: the extraction does not yet record them. The final
   review's independent count differed (about 120 / 131 of 251).

   Recommendation for M1c: re-extract each condition's source text, and evaluate it with a restricted expression
   evaluator (Python `ast`, allowing names, numbers, comparisons, `and`/`or`/`not`, `abs`, `in` and lists only).
   This keeps no pydyna at runtime and runs no arbitrary code.
3. **Type-dependent links** use the `link_by` overrides. The field reader needs the type field's value before it
   resolves the reference.
4. **Separate id namespaces.** ICFD parts are not structural parts. The index must key definitions by kind, and
   ICFD_PART is a kind of its own.
5. **"0 or blank means no reference"** is a global rule. M0 showed `arcctl = 0` misread as Node 1.
6. **Include transforms.** `*INCLUDE_TRANSFORM` offsets (`idnoff`, `ideoff`, `idpoff`, …) are ordinary fields in
   the data, with nothing marking them as id offsets. M1b's include resolver must apply them by name.
7. **Override targets** use four forms: `field`, `fields`, `card` (a series by its name, e.g. `points`,
   `elements`) and `option`. They apply to one `keyword`, a `keywords` list, or a `keyword_prefix` with optional
   `exclude_prefix`. `deckcheck.keywords.override_targets()` expands them, and `test_override_lint` proves each
   override can fire.
8. **Two `_ID` conventions.** For most keywords `_ID` is an option card (`BOUNDARY_SPC_SET_ID` resolves to
   `BOUNDARY_SPC_SET` with option `ID`). For 119 keys pydyna has a separate `X_ID` class (`AIRBAG_*_ID`,
   `DATABASE_*_ID`, …), which resolves to `X_ID` with no options. Consumers must not infer "has an ID card" from
   `Resolved.options` alone, and an override for `X` must also list `X_ID` where both exist.

## 5. Spec §12, first open question, answered

pydyna's data does **not** mark sign-encoded references (negative CN → curve needed an override). It does **not**
mark `*INCLUDE_TRANSFORM` offsets as offsets: they are plain fields, and M1b applies them by name.
