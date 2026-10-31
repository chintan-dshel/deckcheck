# M2b: the VS Code extension

Branch `m2b`, plan `docs/plans/2026-10-30-m2b-extension.md`, spec `docs/specs/2026-10-30-m2-vscode-design.md`.
M2b is the client half of M2: a thin TypeScript extension in `editors/vscode/` that runs M2a's language server with
any Python 3.11+ and installs as a local `.vsix`.

## 1. What M2b delivers

- **Package:** `deckcheck-0.1.0.vsix`, 1.18 MB, 542 files: `bundled/libs` (deckcheck, pygls 2.1.1, lsprotocol,
  attrs, cattrs, typing_extensions; pure Python, 7.6 MB unpacked), `out/src` (the client), and the client's
  `node_modules` (vscode-languageclient 10.1.2 and its dependencies). `NOTICE` lists every bundled package and its
  licence. Built by `npm run package` in `editors/vscode`.
- **Language:** `keyword-deck` for `.k`, `.key`, `.dyn`, no grammar; field hints hidden until Ctrl+Alt.
- **Settings:** the eight of spec §8.
- **Commands:** Show status, Check this model now, Pause for this workspace, Resume, Select Python interpreter.
- **Status bar:** `deckcheck`, `N not checked`, `big model, click to check`, `checks on save`, `paused`,
  `paused (needs more than N MB)`, `no Python`, `check failed`, `stopped`, `save to check`.
- **Python:** `deckcheck.interpreter`, else the Python extension's interpreter, else `py -3`/`python3` on PATH;
  3.11+ checked, else one notification and `no Python`.
- **Process:** the server is started with `bundled/libs` on `PYTHONPATH`; exit code 75 pauses it (never restarted);
  other exits restart it up to 5 times in 3 minutes, then `stopped`; stop always kills the whole process tree
  (`taskkill /T`); start, stop, restart, pause and deactivate run one after another.
- **Large files:** VS Code does not hand files over 50 MB to extensions, so the client finds deck tabs itself;
  a file over `maxSyncMB` is reported to the server once per opening, 10 s after its tab opens, and not at all if
  the tab closed first.

## 2. Decision taken during M2b (Chintan, 2026-10-30)

**Big models are checked on demand and on save, not on open.** A model is big when its last full check took longer
than `liveThresholdSeconds` (2 s), or, before it has been checked, when its size × 0.4 s/MB reaches that (measured:
the LS-DYNA bumper, 18 MB, 6 s; the CCSA Yaris, 161 MB, 63 s). Opening a big model shows "big model, click to
check"; a click, the command or a save runs the check. Why: a full-vehicle check running in the background made
opening another huge file about a third slower for the minute it ran (1.70 vs 1.28 s on this 7.7 GB laptop). The
minute of load is now the engineer's choice.

## 3. Tests

| Layer | Result |
|---|---|
| Unit (`npm test`, Node's runner) | 11 pass: version floor, sync limit, restart policy, status text, excludes, notify-once, once-per-opening; spawn with bundled libs, ping, process-tree kill (the `py` launcher's child included), exit 75 |
| Integration (`npm run test:vscode`, real VS Code) | 7 pass: squiggles, activation under 100 ms, include opened alone has no false DC001, pause and resume, memory pause not restarted, a setting change restarts exactly once, a killed server is restarted |
| Clean profile (`npm run test:clean`) | the `.vsix` installed into an empty profile works with a Python that has no deckcheck installed; negative control: a `.vsix` without `bundled/libs` fails (status `stopped`) |
| Server (pytest) | M2a's suite plus the new behaviours below |

## 4. Harm gate, end to end (CCSA Yaris, `DECKCHECK_HARM=1`)

| Measurement | Result |
|---|---|
| Activation | 1.3 ms installed |
| Editor command during a Yaris check | worst 1.2–2.1 ms (limit 100) |
| Open a 1 KB standalone deck, interleaved on/off | 40 vs 40 ms |
| Open the 10 KB main deck, idle | 49 vs 44 ms (within the 20 ms floor) |
| Open the 169 MB include, idle, interleaved pairs | median pair difference −199 ms (on faster): no measurable cost |
| Open the 169 MB include during an opt-in Yaris check | 1748 vs 1297 ms: reported, not gated (the engineer asked for that check) |
| Large include → click to check → checked | 69 s |

**How the open-time gate is judged** (changed during M2b; Chintan to confirm): within 10 % or under 20 ms, because
a 50 ms open varies by ±10 % between identical runs; for interleaved pairs, on the median of the pair
differences, because single opens of the 169 MB file range 0.9–2.1 s either way and two group medians swung by
more than 10 % between identical runs.

## 5. What the harm gate found, and the fixes

Every task's planned tests passed; the measured gate found six harms and one flawed test of my own:

1. **A large tab was re-requested on every tab event** (VS Code fires them on focus changes), and each request made
   the server discard its running check and start over: the 169 MB include took 133 s instead of 63 s. Now once
   per opening (`newlyOpened`), cancelled if the tab closes first.
2. **The check started while VS Code was still loading the file** (2 s after the tab opened): opening the 169 MB
   include was about a quarter slower. Now 10 s later; with the check held back, no slowdown.
3. **A running check competed for the disk:** the server now runs in Windows background processing mode (CPU,
   disk and memory priority lowered). Cost: the Yaris check 62.5 → 68.5 s.
4. **Closing and reopening an unchanged main deck restarted its one-minute check** each time; an unedited close
   triggered a check too. Reopening a file not modified since its models were checked, and closing a file never
   edited, now start nothing.
5. **About 1 GB of parsed files stayed resident after a model's files were closed** (no check ran to release them).
   Closing a model's last file now frees them in the worker: measured 1148 → 70 MB.
6. **A full-vehicle check slowed opening other huge files while it ran:** resolved by the decision in §2.
7. **My own test was flawed:** its "idle" phase overlapped a real check, and off/on samples were taken in blocks,
   so drift fell on one side. The gate now waits for that check, interleaves the pairs, and uses a 1 KB standalone
   deck to isolate the client's own cost (none).

Also found and fixed on the way: a race where a setting change during a start left no server; TypeScript 6 no longer
including `@types` by default; `ELECTRON_RUN_AS_NODE`, set when tests are launched from inside VS Code.

## 6. Not done in M2b

- Marketplace and Open VSX publishing (needs Chintan's yes; his hands-on trial of the `.vsix` comes first).
- A JavaScript bundler (vsce warns about 185 JS files; installed activation measured 1.3 ms).
- Remote, WSL and Codespaces workspaces: untested.
- M2c: hover, go to definition, find references, outline, field hints.
