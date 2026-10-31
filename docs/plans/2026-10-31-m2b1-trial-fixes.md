# M2b.1: fixes from Chintan's hands-on trial

**Goal:** close the trial's findings (kit `C:\Users\DELL\Desktop\deckcheck-trial\FINDINGS.md`, 2026-10-31) before M2c.
**Spec:** docs/specs/2026-10-30-m2-vscode-design.md (do no harm, §3; harm gate, §10.1) and the M1 spec's finding
classes (docs/specs/2026-10-27-deckcheck-design.md §5).
**Execution:** native, on branch `m2b1`, TDD per task, harm gate at the end. Chintan asked for the work to proceed
while he is away; the merge stays his choice.

## Bracketing
- Ceiling: every finding closed, and each fix shown by a test that failed before it.
- Target: an engineer always knows whether deckcheck is working, what it covered, and when a save is needed;
  paste mistakes LS-DYNA rejects or silently accepts are reported.
- Floor: today's behaviour (silent 70 s check, restart on repeat click, silent blank ids).

## Global constraints
Do no harm (spec §3): no popups for live checks of small models; progress only for big-model checks; nothing waits
on a check. No new finding without LS-DYNA as referee (R16.1 Student, `bakeoff/lsdyna_oracle.py`). Zero false alarms
on the corpus (tier 1, VIVA+, Yaris). Commits end with the Co-Authored-By line.

## LS-DYNA verdicts (2026-10-31, scratchpad probe on the M1d base model)
| Case | LS-DYNA |
|---|---|
| `*PART` mid blank or 0 | rejected: Error 10304 "MATERIAL ID 0 does not exist" |
| `*PART` secid blank | rejected: Error 10125 |
| `*ELEMENT_SHELL` pid blank | rejected: Error 20389 |
| extra `*MAT_ELASTIC` with id blank (card shifted 3 columns right), or id 0 | accepted, no warning |
| extra `*SECTION_SHELL`, `*PART`, `*DEFINE_CURVE`, `*SET_NODE_LIST`, `*HOURGLASS` with blank id | accepted, no warning |
| two `*MAT_ELASTIC` with id 0 | rejected: "Multiply defined MATERIAL ID 0" |

## Tasks
1. **Repeat click and progress (server).** Runner: an explicit check of the model already being checked, with no
   change since it started, is answered "already checking" (it restarted the check before). Runner reports the start
   of a big model's check (with an estimate) and an edit to a big model ("save to check"). `deckcheck/status` gains
   `checking {estimate}` and, on a result, `summary {files, mb, seconds, errors, warnings, explicit}`.
2. **Progress and result (client).** A spinner with elapsed / estimated seconds while a big model is checked; a
   notification for an explicit check; on its end, a message naming what was covered and what was found, with
   "Show Problems". "Check this model now" warns about unsaved changes in a file too big to sync ("Save and check").
3. **Resume.** Measure resume-to-squiggles; status says "starting" from the moment a start begins.
4. **Blank required references (DC001, error):** `*PART` mid and secid, `*ELEMENT_SHELL` pid, blank or 0.
5. **Definitions with a blank id (DC003, warning):** MAT, SECTION, PART, HOURGLASS, DEFINE_CURVE, SET_* families,
   only when the card has other content (a blank card is never an instance's id). Corpus gate: zero new findings
   unexplained.
6. **Leftovers:** memory-pause buttons ("Raise the limit" / "Keep paused", spec §3); `-P` on the server launch and
   preflight; README reload hint (both READMEs).
7. **Gate:** Python suite, unit, integration, harm gate, clean profile, corpus; fresh-reviewer final review.
