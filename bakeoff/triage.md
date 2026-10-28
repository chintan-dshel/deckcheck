# M0 triage — tier 1 (35 LS-DYNA documentation decks), 2026-10-28

Evidence: `results/corpus_tier1.jsonl` (dynars probe), `results/tier1_lsdyna_input.jsonl` (LS-DYNA R16.1 Student
input phase, via `tier1_input_oracle.py` on a scratch copy of the documentation folder).

Referee: a deck LS-DYNA reads to "initialization completed" has every reference resolved, so every dynars Error
on it is a false alarm. LS-DYNA was stopped at that line; nothing was solved to completion except one rerun.

## Summary

| Rule | Findings | Real | False alarm | Undetermined | Line correct |
|---|---|---|---|---|---|
| references_resolve (Error) | 46 | 0 | 46 | 0 | 33 / 46 |
| include_missing (Error) | 6 | 6 | 0 | 0 | 0 / 6 (always line 0) |
| duplicate_ids | 0 | — | — | — | — |
| unreferenced_entities (Warning) | 106 | — | ≥ 5 confirmed by mechanism | rest | 106 / 106 |

Parse: 35 / 35 decks, no crashes; largest parse 0.05 s; peak 181 MB (EX04 post-buckling).
Round-trip: 83 / 83 files byte-identical. One-field edit: `in_place`, 1 line changed, on all 30 decks with a `*PART`.

## references_resolve: 46 false alarms, three mechanisms

| Mechanism | Count | Keywords |
|---|---|---|
| `_ID` option not handled: the leading ID card is read as the first data card | 26 | CONTACT_DRAWBEAD_ID (15), CONTACT_FORCE_TRANSDUCER_ID (3), BOUNDARY_PRESCRIBED_MOTION_SET_ID (2), CONTACT_FORMING_ONE_WAY_SURFACE_TO_SURFACE_ID (2), CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR_ID, CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID, BOUNDARY_SPC_SET_ID, BOUNDARY_PRESCRIBED_MOTION_RIGID_ID |
| ICFD / mesh id namespace: ICFD part ids checked against structural *PART | 13 | ICFD_PART_VOL (4), MESH_VOLUME (4), ICFD_BOUNDARY_FSI / _FREESLIP / _NONSLIP / _PRESCRIBED_VEL, MESH_SURFACE_ELEMENT, SET_PART_LIST_TITLE (ICFD part) |
| Wrong reference type or misread field | 7 | CONTACT_AUTOMATIC_NODES_TO_SURFACE (2, set type depends on SSTYP), BOUNDARY_PRESCRIBED_MOTION_RIGID (rigid part read as node), CONTROL_IMPLICIT_SOLUTION (`arcctl = 0` reported as Node 1), CONSTRAINED_RIGID_BODIES, FREQUENCY_DOMAIN_RANDOM_VIBRATION_FATIGUE |

Worked examples:
- bolts001 `*BOUNDARY_SPC_SET_ID`: card 1 is `id = 24, heading = FIXED`; dynars reports "NodeSet 24 not defined".
  LS-DYNA run from the parent folder: normal termination.
- beam_sub `*CONTROL_IMPLICIT_SOLUTION` card 3: `arcctl = 0` (off); dynars reports "ARCCTL references Node 1".
  (LS-DYNA rejected beam_sub for an unrelated runtime reason: it needs `master.isf` from the master model run.)

## include_missing: 6 real

eigen001, doorstiff001, bolts001 `*INCLUDE INCLUDE_FILES/...`: the folder is a sibling of `EXAMPLES/`. LS-DYNA run
from the deck's folder: "File INCLUDE_FILES\control_cards_linear.key does not exist" (Error 10087). The decks
work only when launched from the parent folder. Real by LS-DYNA's own reading; line reported as 0.

## unreferenced_entities: 106 warnings, partly triaged

LS-DYNA does not report unused definitions, so there is no oracle. `unused_first_pass.py` searched each id as a
token in other blocks. Its matches are too noisy for small ids, so it gives no full classification. Five warnings
are confirmed false by mechanism:
- crashbox Curve 422 is used in `*DEFINE_TABLE` (tables of curves are not followed).
- cross_member_op10 Curve 8 is used by `*CONTACT_DRAWBEAD_ID` (the `_ID` mechanism above).
- bolts001 PartSet 6 is used by `*CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID` (`_ID`).
- EX09 Curve 1 is used by `*AIRBAG_SIMPLE_PRESSURE_VOLUME_ID` through `cn = -1` (a negative CN means |CN| is a
  load-curve id): a fourth mechanism, sign-encoded references.
- spr4 Curve 4 is used by `*BOUNDARY_PRESCRIBED_MOTION_RIGID_ID` (`_ID`).

Not classified: the remaining 101. Any of them sharing a mechanism above is false; the rest may be genuine leftovers.

# Tier 2 — VIVA+ 50M seated v2.0.2, 2026-10-28

Evidence: `results/corpus_tier2.jsonl`.

| Rule | Findings | Real | False alarm |
|---|---|---|---|
| include_missing (Error) | 16 | 0 | 16 |

The root deck sets `*INCLUDE_PATH ../common/` (and `..\common\`). All 16 body-region includes (`vivaplus-10-Head.k`
… `vivaplus-materials.k`) are present in `model/common/`. dynars ignores `*INCLUDE_PATH` (the same defect as torture
case `include_path`, where LS-DYNA reads the include), so it parsed **2 files** of the model (root + nodes) and
reported the body as missing. No other rule could see the model's parts, materials or contacts. Parse 0.45 s, peak
152.5 MB; round-trip 2/2; edit not tried (no `*PART` in the two files it loaded).

# Tier 2 — CCSA 2010 Toyota Yaris detailed v2j, 2026-10-28

Evidence: `results/corpus_tier2_yaris.jsonl`. Root `combine.key`, 4 files (169 MB main deck, 1,519,587 elements).
No LS-DYNA referee: the model exceeds the Student version's size limit. Triage by reading the deck. Run with a 2 GB cap
(not 4 GB) per the laptop's bounded-resource rule.

Parse and checks: 4/4 files loaded (`*INCLUDE` and `*INCLUDE_TRANSFORM` resolved); rules 0.22 s; peak 953 MB.
Round-trip 4/4 identical; one-field edit `in_place`, 1 line changed.

| Rule | Findings | Real | False | Unclassified |
|---|---|---|---|---|
| references_resolve, include_missing, duplicate_ids | 0 | — | — | — |
| unreferenced_entities (Warning) | 13 | 0 | 9 | 4 |

False, each verified at the field:
- Transform 1000001: used as `tranid` of `*INCLUDE_TRANSFORM` (combine.key 101); it positions `wall.key`.
- NodeSets 1000011–1000014: used as `nsid` of `*RIGIDWALL_PLANAR` (combine.key 238 and the same pattern after).
- Sets 5000004–5000007: used as `nsid/pid` of `*INITIAL_VELOCITY_GENERATION` (set-yaris 224–236; wheel spin and
  vehicle velocity).

Unclassified: PartSets 2000003–2000006. Their ids coincide with part ids used on thousands of lines, so a text search
cannot decide them.
