# deckcheck backlog

Everything deferred, declined or pinned, in one place. **Rule (2026-10-31):** every plan's deferred minors, its
"declined to judge" rulings and any pinned decision land here in the commit that closes the plan. A plan's working
ledger is deleted at the end; this file is the record. Rebuilt today from the session transcripts, so items from
M0 to M2b.1 that were only ever in a ledger or a chat are back.

Status: **open**, **done** (with where), or **pinned** (waiting on Chintan).

## Pinned decisions
| Item | Status |
|---|---|
| Release: PyPI (CLI) and Open VSX / Marketplace (extension) | pinned: Chintan sleeping on it (2026-10-31). Needs his explicit yes and his trial first |
| Re-trial of M2b.1 (TRIAL.md steps 2-5, ~10 min) | pinned: next time at the laptop |
| Private GitHub remote | done 2026-10-31: github.com/chintan-dshel/deckcheck (private), main pushed |

## Product backlog (larger items)
| Item | Why | Status |
|---|---|---|
| Client status as a per-model state machine (`logic.ts`), status bar follows the active file's model | both M2b.1 state bugs and the recurring "status names the last model announced" lived in loose module variables | done (branch client-state: `StatusBoard`; fresh review: 3 Important fixed) |
| M2c: hover, go to definition, find references, outline, field ruler hints | spec stage M2c | open |
| Notepad++: a tested NppExec recipe for the CLI, in the README | Chintan's trial: many engineers use Notepad++ | open (after M3) |
| Other LSP editors (Neovim, Sublime, Emacs, Kate, JetBrains) | squiggles work through any LSP client; harm gate is VS Code only | open (on request) |
| Incremental model index (live checks on big models) | trial finding 7 | declined by Chintan: save-to-check with clear messages is enough |
| Test on a real multi-occupant industrial model | the heaviest real model so far is one vehicle (Yaris); do-no-harm matters most there | open (needs a model; results stay names, counts, lines) |
| Required references beyond PART mid/secid and ELEMENT_SHELL pid (solids, beams, PART_* variants) | only what LS-DYNA was asked is reported | open (needs LS-DYNA referee cases) |
| Two definitions with id 0: DC002 error instead of two DC003 warnings | LS-DYNA rejects "Multiply defined MATERIAL ID 0" | open |
| Cancel for a running check | a check can't be interrupted without M1 core changes; Pause stops it | open |
| Remote, WSL and Codespaces workspaces | untested | open |
| Debloat pass (dead code, duplicate logic) | 21-day reminder due | open |
| User manual and public roadmap (`docs/manual/`, `docs/roadmap.md`) | Chintan, 2026-11-01: ready for the public repo, shows it is a work in progress | done (branch docs-manual) |
| Extension icon | the extension page shows VS Code's generic placeholder (manual screenshot) | open (release prep) |
| Extension README links to the manual | relative links break inside a .vsix; needs the public GitHub URL | open (release prep) |
| Screenshot rig in the repo | the manual's screenshots were made by a throwaway driver extension + capture script (session scratch); re-shooting after a UI change means rebuilding it | open (if screenshots go stale) |

## Deferred minors

### M0 (dynars go/no-go)
- open: probe `_line_ok` prefix match lacks a keyword boundary (`*PART` matches `*PARTICLE_BLAST`)
- open: `run.py` reads stderr only at exit; a noisy child could stall to its timeout
- open: `tier1_input_oracle.py` hard-coded paths; its "timeout" label also covers exited-without-marker
- open: `run.py` TORTURE/MANIFEST are cwd-relative; mixed relative/absolute deck paths
- open: parameter case missing from the clean-case parametrization in `test_probe.py`
- open: `changed_lines` is weaker than the spec's "only that field's bytes differ"
- open: in_place entries pin only the root file's hash, not includes

### M1a (keyword data)
- open: evidence-method caveats stated in the report, not re-run with INCLUDE_PATH / long-format awareness
- open: DEFINE_TABLE lcid-column reading to be settled by a torture case
- open: unreachable keys with spaces or lowercase (`MAT_115_o`, `ELEMENT_SOLID_DOF (ten nodes format)`)
- open: format-suffix edge cases `*X - extra`, `+-` silently give format ''
- open: `test_keyword_names_are_unique` is vacuous; the raise in `extract_all` is the real guard
- open: `type_field_evidence` unused import, list-based `seen`

### M1b (reader and includes)
- open: Unicode whitespace handling (the original note was cut off in the record; re-check)
- open: `reader._name` splits on tabs, `keywords.resolve` on spaces only
- open: a continuation name's column span includes the ` +`
- open: `m1b_reader.jsonl` stores machine-absolute deck paths
- open: `PATH_APPLIES_EARLIER` second pass is dead code and would re-append paths if enabled
- open: `lsdyna_oracle` records a solver timeout as "rejected"

### M1c (field reader and index)
- open: `params._pairs` ignores LONG=Y and `+` (degrades to UNKNOWN)
- open: `_long_deck` re-reads the whole main file
- open: no `*SET_PART_LIST` blank-row test (behaviour verified by a reviewer probe)

### M1d (checks and CLI)
- open: a tab inside a comma card or trailing a fixed card gets the same "misreads" message; only between-field tabs are refereed
- done (README known limits, M1d/M2b.1): README overstated DC003 scope
- open: DC004 cycle message "includes itself" is wrong for A->B->A
- open: a PermissionError on an include prints "internal error (please report this)"
- open: "no such file" for a path that is a folder
- open: DC005 evidence text should say the audit guarantees other referrers are linked

### M2a (language server)
- open: `scan()` can lose a `mark_dirty()` that arrives during a long scan
- done (M2b, PagefileUsage): the memory watchdog measured the working set. open: it ignores a `GetProcessMemoryInfo` failure
- open: the check-failure log carries `repr(error)`, not the traceback
- done (M2b, `deckcheck/active`): `runner.active` was never set
- open: models named by file name only; two `main.k` in different folders read alike
- open: merge collapses two identical findings from one model
- open: `did_close` does not mark the scan dirty
- open: `mainDecks` resolved against the first folder only in multi-root workspaces
- open: `_lines` is quadratic on a huge file with no newline
- open: `_open` rebuilds ctypes prototypes per call; the handle leaks if `open_osfhandle` fails
- open: the server imports `__main__` as a module (two copies of the watchdog code)
- open: merging and JSON-encoding very many diagnostics run on the protocol thread
- open: typing in an on-save model wakes the worker and drains the typed file on each keystroke

### M2b (extension)
- open: `did_save` does not clear `edited`, so a close after edit+save+check re-checks
- open: `deckcheck/opened` skips the unchanged-since-checked test (reopening the 169 MB include asks again)
- open: the click-to-check status clears the last check's "not checked" items
- done (M2b.1): the memory-pause notification offered the wrong buttons
- done (M2b.1): `python -m` put the launch folder first on `sys.path` (now `-P`)
- open: one FileSystemWatcher leaks per restart
- open: `killTree` returns early if the launcher already exited, orphaning a still-running child
- open: `enable: false` shows as "paused", indistinguishable from Pause
- open: settings read without a resource scope (multi-root per-folder settings ignored)
- open: `findPython` activates the Python extension when installed
- open: `deckcheck.interpreter` not marked restricted for untrusted workspaces
- open: docs: spec §3 row still says BELOW_NORMAL only

### M2b.1 (trial fixes)
- open: `_on_start` stats every model file on the protocol thread for a model's first check (spec §3)
- open: the server's own "already checking" reply can only arrive after the check ended; now rarely reachable
- open: runner `_running` not reset if `big()` / `on_start` raises (try/finally)
- open: the missing-include note is appended to the required-blank DC001 message
- open: `blank_defs` ignore `*INCLUDE_TRANSFORM` offsets (unrefereed)
- open: `_span` uses the 10-wide slot for blank fields in LONG / `+` and free-format cards (squiggle width)
- open: "Check this model now" prompts about every dirty large tab in the window, not only the model's
- open: an edit during a big model's own check: "save to check" is overwritten by the result's status

### Client status board (branch client-state)
- open: `stop(false)` from the language client's close handler runs outside the serial chain; its `forgetModels()` can wipe a newer client's records for a moment
- open: a check discarded as stale keeps its first start time and estimate until the re-run reports ("longer than estimated")

## Declined-to-judge rulings still standing (cost if wrong)
- Excluded files are still checked when opened by hand (an excluded giant file opened by hand is checked).
- Watcher events for decks in no model trigger lone checks (stray statuses).
- `files.exclude` matched with fnmatch (an exclude matching more or less than meant).
- A model whose only open file is unsynced loses its parses after each check (re-reading 170 MB per opted-in check).
- Very low disk priority can slow an opted-in check behind antivirus or sync tools.
- `on_edit` sends a status per keystroke on a big model (status churn while typing).
- Summary popup after a save only when the check took 10 s or more (a 6-9 s save ends with a status-bar change only).
