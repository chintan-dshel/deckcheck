# deckcheck M2: VS Code extension — design

Status: approved 2026-10-30; M2a done 2026-10-30 (`docs/m2a-server-squiggles.md`); M2b done 2026-10-31
(`docs/m2b-extension.md`). Binds M2a, M2b and M2c. Parent spec:
`docs/specs/2026-10-27-deckcheck-design.md` (§8 front doors, §12 edge-case register).

## 1. Goal and bracketing

M2 brings M1's checks into the editor: squiggles as you work, and navigation across a model's include files, for
decks of any size, without ever making VS Code worse at opening or editing a deck.

| | M2 |
|---|---|
| Ceiling | An LS-PrePost-class editor: live squiggles, hover docs for every field, definition, references, rename, completion, outline |
| Target | Squiggles, hover, go-to-definition, find references, outline and field hints, include-aware, responsive on a full-vehicle model |
| Floor | A VS Code task running the M1 CLI with a problem matcher on `file:line:col` (about an hour, no new Python) |
| Gap to close | Unsaved-text feedback, the right main deck for an include file, navigation, and staying harmless on heavy models |

Measured on 2026-10-30 (M1 core, this laptop): a full check takes 2 ms on a test deck, 6 s on the LS-DYNA bumper
benchmark, 63 s and about 1.1 GB on the CCSA Yaris. A full check per keystroke is therefore impossible on big
models; M2 adapts instead (§6).

## 2. Decisions (Chintan, 2026-10-30)

| Decision | Choice | Why |
|---|---|---|
| Which deck is checked when an include file is open | Auto-detect the main deck(s) that include it; `deckcheck.mainDecks` overrides | Checking an include alone gives false DC001 errors |
| When checks run | Adaptive: as you type when the model's last check took under 2 s, otherwise on open and save; revised in M2b to on demand and on save for big models | Small decks feel live; big ones don't burn a core per keystroke; a background full-vehicle check slowed other opens (§6) |
| Python | deckcheck and pygls bundled inside the extension, run by any Python 3.11+ | No pip install for the analyst; works before any PyPI release |
| Hover content | Structure and resolved references only; no descriptions | pydyna's help text traces back to the keyword manual (parent spec: never copy it) |
| Features | Squiggles, hover, definition, plus find references, outline, field hints | Each is a query on the index M1 already builds |
| Architecture | In-process pygls server calling the core directly | Least new code; unsaved text and the index are reachable |
| Defaults | Memory budget 2 GB, files above 20 MB not synced | The corpus cap; the Yaris fits, four VIVA+ occupants don't |
| Principle | **Do no harm** (§3) | Engineers should choose deckcheck because it helps, never tolerate it despite problems |

## 3. Do no harm

deckcheck must never make opening, scrolling or editing a deck slower or less reliable. If it can't help safely,
it gets out of the way, and the file is shown exactly as VS Code shows it without the extension. This rule outranks
every feature: a feature that can't meet it ships disabled or not at all.

| Harm | Design |
|---|---|
| Slower rendering | deckcheck never takes part in drawing text: no syntax grammar, no semantic tokens, no decorations in M2. Squiggles are drawn by VS Code. Field hints are computed only for the visible range, from the last result, capped (§5.6). |
| A slower VS Code | The extension host is shared with every other extension, so the client reads and parses nothing. Activation returns at once; the server starts in the background. All work is in the separate Python process. |
| Huge files held twice in memory | Files above `deckcheck.maxSyncMB` (20) are not sent to the server; the server reads them from disk and checks them on save. |
| Requests stuck behind a check | No request waits for a check. Hover, definition, references, outline and hints answer from the last index or return nothing. |
| The machine slowing down | The server runs at below-normal CPU priority (Windows `BELOW_NORMAL_PRIORITY_CLASS`, POSIX `nice 10`). One check at a time across the workspace. |
| A model too big | The server samples its own memory (no dependencies: `GetProcessMemoryInfo` on Windows, `/proc/self/statm` on Linux, `getrusage` on macOS) every 250 ms. Over `deckcheck.memoryMB` (2048) it exits with code 75; the client does not restart it and shows "deckcheck paused: this model needs more than 2 GB", with "Raise the limit" and "Keep paused". |
| A crash loop | Restarts are limited to 5 in 3 minutes, then deckcheck stays off. At most one notification per cause per session, never a modal dialog. |
| Orphaned processes | Stopping the server always kills the whole process tree: a venv's `python.exe` starts the real interpreter as a child. |

Off switches, each effective at once (server stopped, files untouched):
1. Status bar: "Pause deckcheck for this workspace" (remembered per workspace).
2. Settings: `deckcheck.enable`; `deckcheck.exclude` globs, e.g. a giant mesh include.
3. VS Code's own Disable for the extension.

## 4. Architecture

```
VS Code ── extension host ── client (TypeScript, thin) ──stdio JSON-RPC── server (Python, low priority)
                                                                          ├─ workspace.py  overlay, parse cache, models
                                                                          ├─ runner.py     one check at a time, adaptive
                                                                          ├─ features.py   hover, definition, references,
                                                                          │                outline, hints from last index
                                                                          └─ deckcheck core (M1): resolver, index, rules
```

### 4.1 Client (`editors/vscode/`)
- Contributes the language `keyword-deck` (alias "Keyword deck (LS-DYNA)") for `.k`, `.key`, `.dyn`, with no
  grammar. Activates on `onLanguage:keyword-deck`. The document selector is by file pattern, so a deck opened under
  another extension's language id is still served once deckcheck is active.
- Interpreter: `deckcheck.interpreter` if set, else the Python extension's active environment (if installed), else
  `py -3` / `python3` on PATH. Below 3.11 or none: one notification with "Select interpreter"; status `deckcheck: no
  Python`; nothing runs.
- Launches `<python> -m deckcheck.lsp` with `bundled/libs` first on `PYTHONPATH`.
- Owns: the status-bar item (§5.1), the off switches, the sync limit (middleware drops `didOpen`/`didChange` for
  files above `maxSyncMB` and tells the server to read them from disk), process-tree kill, the exit-code-75 rule.

### 4.2 Server (`src/deckcheck/lsp/`, extra `deckcheck[lsp]`, pygls 2.x)
- `workspace.py`: the overlay (unsaved text of synced documents), a parse cache keyed by path and content version,
  main-deck detection (§4.4), the model registry.
- `runner.py`: §6.
- `features.py`: §5.
- `server.py`: protocol handlers only; each calls the three modules above.
- `__main__.py`: sets priority and a 0.1 ms GIL switch interval, starts the memory watchdog, runs the server on
  stdio.
- Protocol additions (M2a): client → server notification `deckcheck/check {uri}` (check the models of a file the
  client does not sync); server → client notification `deckcheck/status {main, state, notChecked}` with state
  `ok | checks on save | check failed | save to check`; request `deckcheck/ping` → `{ok: true}`; exit code 75 =
  paused over the memory budget. Settings arrive as `initializationOptions`.
- Keeping the protocol thread responsive (M2a, measured on the Yaris): checks run with automatic garbage
  collection paused and survivors frozen; files are read and split a megabyte at a time; big results are converted
  and freed in the worker, a chunk at a time. Ping during a Yaris check: 16 ms worst (was 515 ms).

### 4.3 Changes to the M1 core (minimal, test-first, CLI output unchanged byte for byte)
- `resolve_tree(main, source=None, cache=None)`: `source(path) -> str | None` supplies overlay text; the existing
  per-file cache (`includes._build`) is passed in and kept between runs.
- `_long_deck` reads through the same source instead of re-reading the main file (closes M1c deferred minor M4).
- Index lookups by position: `Index.at(path, line, col)` → the definition or reference under the cursor, and
  `Index.uses(kind, id)` → every reference to an id. Positions already exist in the index (packed locations).

### 4.4 Main-deck detection
- `deckcheck.mainDecks` set for the folder: those are the models; a file in none of them is checked alone.
- Otherwise: a light include walk over deck files in the workspace (respecting `files.exclude` and
  `deckcheck.exclude`). It applies M1b's location rules (main deck's folder, then `*INCLUDE_PATH` folders; never the
  including file's folder) but reads only `*INCLUDE*` blocks, streaming, at low priority. Roots are files nothing
  includes. An open file's models are the roots whose walk reaches it; if none, the file is its own main deck.
- A file whose model is not yet known waits for the scan instead of being checked alone.
- Parity: for every torture and corpus deck, the light walk's file set equals `resolve_tree`'s.
- A file in two models gets both models' findings; identical findings are shown once, others name their model.

## 5. Features

### 5.1 Diagnostics and status
- Every M1 diagnostic becomes an LSP diagnostic: severity, code (linked to the README check table), message,
  `related` as related information. Columns are converted to UTF-16 units of the text the editor shows: a file read
  from disk is mapped through UTF-8 decoding with replacement (VS Code's default), editor text is counted directly
  (`lsp/convert.py`). (Revised in M2a: the draft said columns carry over unchanged, which is wrong for UTF-8 files.)
  No link to the README yet: there is no public URL until the release decision.
- Diagnostics are published for every file of a model; files that no longer have any are cleared. `deckcheck.ignore`
  matches the CLI's `--ignore`.
- "Not checked" never becomes a diagnostic. The status bar shows `deckcheck: N not checked` (or `checks on save`,
  `paused`, `no Python`, `check failed`); clicking it lists the items and offers Pause.

### 5.2 Hover
On a field value: field name, columns, type, default, the value as read (after `*PARAMETER`), and for a reference
where it points: `mid → MAT 1, *MAT_ELASTIC at materials.k:12`, or "not defined", or "LS-DYNA accepts this but it has
no effect" (DC006). On a keyword line: the keyword as resolved (option suffixes), or "not in deckcheck's keyword data;
passed through". No descriptions.

### 5.3 Go to definition
On a reference: its definition (several for a duplicate). Ids shifted by `*INCLUDE_TRANSFORM` offsets resolve to the
definition the offset produces. On a definition: itself.

### 5.4 Find references
Every use of the id across the model(s), from `Index.uses`. M3's `find_references` reuses this query.

### 5.5 Outline
One symbol per keyword block, named by keyword plus id and title where known (`*PART 1 plate`). Above 10,000 blocks
in one file, no outline is returned (the status item says so), so the panel can't stall.

### 5.6 Field hints and ruler
Inlay hints naming each field at its column. Inline hints push text to the right, which breaks the visual
alignment of a fixed-column deck, so they are hidden by default and shown while Ctrl+Alt is held (language default
`editor.inlayHints.enabled: offUnlessPressed`). Computed for the visible range only, at most 2,000 per request. A
code action, "Insert field ruler", writes a `$#` comment line naming the fields above the card, as pre-processors do.

## 6. Runner
- One worker thread for the whole workspace; a queue keyed by model; the active editor's model first. A newer
  request for a model replaces its queued one; a result older than the newest edit is discarded.
- Adaptive: a model whose last full check took under `deckcheck.liveThresholdSeconds` (2) is re-checked 300 ms
  after typing pauses. A bigger model is checked on demand and on save only (revised in M2b, Chintan
  2026-10-30): opening it shows `big model, click to check`; a click, `deckcheck.checkNow` or a save runs it. Before
  its first check, a model is big when its size × 0.4 s/MB reaches the threshold (measured: bumper 18 MB in 6 s,
  Yaris 161 MB in 63 s). Why: a background full-vehicle check made opening another huge file ~33 % slower while
  it ran.
- Reopening a file not modified since its models were checked, and closing a file never edited, start no check;
  closing a model's last file frees its parsed files (M2b harm gate).
- The last index is kept per model while any of its files is open, dropped when the last closes.
- A whole-check failure clears that model's diagnostics (never stale squiggles at wrong lines), sets
  `check failed`, and writes the traceback to the "deckcheck" output channel.

## 7. Edge cases
- Files changed outside VS Code: a file watcher drops the cached parse and re-queues the affected models.
- Untitled documents: not checked; status `save to check`.
- Includes outside the workspace: resolved exactly as by the CLI; diagnostics appear when opened.
- Multi-root workspaces: settings, detection and models per folder.
- `.k` is also used by other languages; `deckcheck.enable: false` per folder is the way out.
- Remote, WSL and Codespaces: not tested in M2; stated in the README.
- Windows file locks: deckcheck opens files with delete sharing, so deleting a file or saving it in place (VS Code's
  way) works while deckcheck reads it. Windows still refuses replacing a file by rename while any program has it
  open; deckcheck keeps a file open only while reading it.

## 8. Settings

| Setting | Default | Meaning |
|---|---|---|
| `deckcheck.enable` | `true` | Off switch per workspace or folder |
| `deckcheck.exclude` | `[]` | Globs never checked or scanned |
| `deckcheck.mainDecks` | `[]` | Main decks; overrides detection |
| `deckcheck.interpreter` | `""` | Python 3.11+ to run the server |
| `deckcheck.liveThresholdSeconds` | `2` | Live checks below this full-check time |
| `deckcheck.maxSyncMB` | `20` | Larger files are read from disk, checked on save |
| `deckcheck.memoryMB` | `2048` | Server pauses above this |
| `deckcheck.ignore` | `[]` | Codes left out, as `--ignore` |

## 9. Distribution and licences
- `.vsix` built locally with `vsce package`; `bundled/libs` filled at build time by `pip install --target` from the
  local source and pygls 2.1.1 (pure Python: pygls Apache-2.0; lsprotocol, attrs, cattrs MIT). Client dependency
  vscode-languageclient (MIT). All listed in `NOTICE`.
- No Marketplace or Open VSX publisher account, and no publish, without Chintan's explicit yes; before any publish,
  Chintan's hands-on trial from dry-run-verified instructions.
- The extension's name and publisher display name are "deckcheck"; descriptions may say "for LS-DYNA".

## 10. Testing
- Core changes: test-first; the full M1 suite stays green; the torture harness proves the CLI unchanged.
- Parity: for all 74 torture decks, server diagnostics equal CLI diagnostics (codes, files, lines, columns).
- Protocol: pytest-lsp (dev only) drives the real server: open, edit, hover, definition, references, outline, hints,
  including references across includes and `*INCLUDE_TRANSFORM` offsets.
- Runner: fake clock and fake durations for the threshold, replacement of queued requests, discarded stale results.
- Detection: folder fixtures for an include opened alone, a file in two models, a cycle, `*INCLUDE_PATH`, a
  `mainDecks` override; the light-walk parity above.
- Client: one `@vscode/test-electron` test: activation, bundled server start, squiggles on `seeded_mistakes`.

### 10.1 Harm gate (measured; a stage fails if any line fails)
- Opening the Yaris main file and its largest include: time to visible text with deckcheck on is within 10 % of off,
  or under 20 ms slower (revised in M2b after seeing data; confirmed by Chintan 2026-10-31). Interleaved on/off
  pairs are judged on the median pair difference. Opening during an opted-in check is reported, not gated.
- Extension activation under 100 ms.
- During a Yaris check, a trivial editor command returns in under 100 ms.
- Stress decks, generated locally, never committed, each run under the 2 GB lab cap; each must end with the file
  open, the editor responsive, and deckcheck working or reporting itself paused:
  - four VIVA+ occupants in one model via `*INCLUDE_TRANSFORM` with id offsets (expected: paused over budget);
  - a single-file mesh of several hundred MB (above the sync limit);
  - a 1 MB single line; binary data renamed `.k`; NUL bytes;
  - a file deleted, and a file locked, during a check;
  - 50 include files open at once; 60 s of fast typing on a small deck;
  - the server killed mid-run.
- New industrial edge cases are added here as lines, one per case.

## 11. Stages and definition of done
Each stage gets its own plan, branch, final review and merge decision.

| Stage | Scope | Done when |
|---|---|---|
| M2a Server and squiggles | §4.2–4.4 core changes, overlay, detection, runner, diagnostics, priority and memory watchdog | Parity on all torture decks; small-deck unsaved edit re-checked within 1 s; an include from VIVA+ and from the Yaris opened with zero false DC001, under 2 GB; server-side stress decks pass |
| M2b Extension | §4.1 client, interpreter discovery, status bar, off switches, sync limit, process-tree kill, `.vsix` | `.vsix` installs in a clean VS Code profile and works with only Python 3.11+; full harm gate (§10.1) passes |
| M2c Navigation | §5.2–5.6 hover, definition, references, outline, hints, ruler action | Every feature passes its protocol tests; harm gate re-run with the features on |

## 12. Out of scope for M2
Syntax highlighting, semantic tokens, completion, rename, quick fixes beyond the ruler, formatting, config files,
the MCP server (M3), Marketplace or Open VSX publishing without an explicit yes.
