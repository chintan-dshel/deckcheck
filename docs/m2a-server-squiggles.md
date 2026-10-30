# M2a: language server and squiggles

Branch `m2`, plan `docs/plans/2026-10-30-m2a-server-squiggles.md`, spec `docs/specs/2026-10-30-m2-vscode-design.md`.
M2a is the server half of the VS Code extension: `python -m deckcheck.lsp` publishes M1's diagnostics for a deck
and its whole model while it is edited, and is built so it can never make the editor worse (spec §3).

## 1. What M2a delivers (the contract M2b's client uses)

- `pip install deckcheck[lsp]` adds pygls 2.1.1; the core still has no runtime dependencies.
- `initializationOptions`: `mainDecks`, `exclude`, `liveThresholdSeconds` (2), `memoryMB` (2048), `ignore`.
- Standard: `didOpen`, `didChange` (incremental), `didSave`, `didClose`, `workspace/didChangeWatchedFiles`;
  `textDocument/publishDiagnostics` for every file of a checked model, included files first, main deck last.
- `deckcheck/check {uri}` (client → server): check the models of a file the client does not sync.
- `deckcheck/status {main, state, notChecked}` (server → client): `ok`, `checks on save`, `check failed`,
  `save to check`. Params reach a pygls client as objects, not dicts.
- `deckcheck/ping` → `{ok: true}`.
- Exit code 75 with `deckcheck: memory budget N MB exceeded; pausing` on stderr: pause, do not restart.
- Main decks are detected by a light include walk (M1b's location rules, `*INCLUDE*` blocks only). It finds exactly
  the files the full resolver finds on every torture deck and all 37 corpus decks, VIVA+ and the Yaris included.
- One check at a time; live re-checks 300 ms after typing pauses when a model's last check took under 2 s,
  otherwise on open and save; a result superseded by a newer edit is discarded.

## 2. Parity

Every torture deck opened through the protocol gives exactly the CLI's diagnostics (codes, files, lines, columns,
messages), with columns mapped to what VS Code shows (`tests/test_lsp_server.py::test_parity_with_the_cli_on_every_torture_deck`).
An unsaved edit on a small deck is re-checked and published in under 1 s.

## 3. Real decks

| Case | Result |
|---|---|
| VIVA+ `common/vivaplus-joints.k` opened | Belongs to 4 models (50F/50M, seated/standing); all checked; 50M diagnostics after 55.5 s (a 2 s scan, then the four models checked in turn); zero DC001 |
| Yaris `set-yaris-detailed-v2j.key` opened | Model `combine.key` checked, 62.5 s; zero DC001 |
| Ping during a Yaris check | worst 16 ms (target 100) |

## 4. Harm gate, server side

`DECKCHECK_STRESS=1` (generated decks, never committed; each run under the server's own 2 GB budget):

| Stress case | Outcome |
|---|---|
| Four VIVA+ occupants via `*INCLUDE_TRANSFORM` with id offsets (every include found) | checked in 48 s, under 2 GB: the four share one parse of the VIVA+ files |
| 304 MB single-file mesh, not synced (`deckcheck/check`) | checked in 40 s; ping after it under 100 ms |
| 1 MB single line; 1 MB random binary as `.k`; NUL bytes | checked, server responsive |
| Include deleted during a check; include locked (Windows) | checked or `check failed`, server responsive |
| 50 open includes, 60 s of typing (1,035 edits) | worst ping 16 ms |
| Memory budget exceeded (`memoryMB: 1`) | exit 75 with the pause message |
| Priority | below normal (Windows `BELOW_NORMAL_PRIORITY_CLASS`) |

## 5. What the harm gate found, and the fixes

The plan's tests passed on first implementation; the measured gate did not. Each finding was measured, fixed and
re-measured:

1. **Ping 437–515 ms during a Yaris check.** A probe of the protocol thread found two causes: 12 full garbage
   collections of up to 221 ms each, and a 207 ms `str.split` of the 170 MB Yaris file, each one C call holding the
   GIL. Fixes: collection paused during checks with survivors frozen afterwards (M1's structures are acyclic);
   files read and split a megabyte at a time (`reader._lines`, identical output, tested across chunk boundaries).
   That left a steady ~100 ms: at a 1 ms or 5 ms GIL switch interval the protocol thread kept losing the hand-off
   on Windows. A benchmark across settings gave a 2 ms median at 0.1 ms, so the server uses 0.1 ms. Worst ping now
   16 ms, Yaris check time unchanged (62.5 s).
2. **Ping 438 ms right after the 304 MB mesh check.** Freeing the 5.5-million-card parse and the index is one C call
   per container (109 ms measured at 2 million nodes), and the cache was released on the protocol thread. Fixes:
   results are converted and freed in the worker; caches, parses and the index are emptied a chunk at a time;
   changed files are only recorded on the protocol thread and freed by the worker before the next check.
3. **Deleting a file failed while deckcheck read it** (Windows `WinError 32`). Windows' default open leaves out
   delete sharing. deckcheck now opens with read, write and delete sharing: deleting and in-place saving (VS Code's
   way) work during a read. Replacing a file by rename is still refused by Windows while any program reads it; files
   stay open only while being read (spec §7).
4. **The first four-occupant test deck loaded only 5 files.** VIVA+ resolves its includes from the main deck's
   folder, as LS-DYNA does, and the test placed its wrapper elsewhere. The test now sits beside VIVA+'s main deck,
   asserts every include is found, and asserts no DC004.

## 6. What M2b needs

- Send settings as `initializationOptions`; files above `maxSyncMB` are not synced: send `deckcheck/check` on their
  save.
- Exit code 75: show "paused", offer raising the budget, never restart. Kill the whole process tree on stop (a venv's
  `python.exe` starts the real interpreter as a child).
- Register file watchers for `.k`, `.key`, `.dyn` (the server already handles `didChangeWatchedFiles`).
- Status bar from `deckcheck/status`; read its params by attribute or JSON.
- Re-run the harm gate end to end with the client: open time on vs off, activation time, command round trip.
