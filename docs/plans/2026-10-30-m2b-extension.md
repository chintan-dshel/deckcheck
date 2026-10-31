# M2b: VS Code Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A thin TypeScript VS Code extension, installable as a local `.vsix`, that runs M2a's language server with any Python 3.11+ (deckcheck and pygls bundled inside), shows squiggles and a status bar, and passes the end-to-end harm gate.

**Architecture:** `editors/vscode/` holds the client. Pure decisions (version floor, sync limit, restart policy, status text, excludes, notify-once) live in `src/logic.ts`, tested with Node's own test runner. `src/process.ts` finds Python, spawns `python -m deckcheck.lsp` with `bundled/libs` on `PYTHONPATH`, reads its exit code and kills its whole process tree. `src/extension.ts` wires vscode-languageclient to those pieces. Integration and harm tests run in a real VS Code via `@vscode/test-electron`.

**Tech Stack:** TypeScript 6.0.3, vscode-languageclient 10.1.2, @types/vscode 1.91.0 (engines `^1.91.0`), @vscode/python-extension 1.0.6, @vscode/test-electron 3.1.0, @vscode/vsce 4.0.0, Node 24 (`node --test` with built-in type stripping), Python 3.11+ (server side, unchanged except Task 1).

**Spec:** `docs/specs/2026-10-30-m2-vscode-design.md` (§3 do no harm, §4.1 client, §5.1 status, §7 edge cases, §8 settings, §9 distribution, §10.1 harm gate, §11 M2b row). Server contract: `docs/m2a-server-squiggles.md` §1 and §6.

## Global Constraints

- Do no harm (spec §3) outranks every feature: activation returns at once; the extension host reads and parses no deck; no modal dialogs; at most one notification per cause per session; restarts limited to 5 in 3 minutes; exit code 75 → paused, never restarted; stopping always kills the whole process tree.
- No Marketplace or Open VSX publisher account and no publish without Chintan's explicit yes. `publisher` in the manifest is the local id `deckcheck`.
- Name and display name "deckcheck"; descriptions may say "for LS-DYNA". No syntax grammar, semantic tokens or decorations.
- Exact dependency versions, each published at least two weeks before 2026-10-30 (listed in Tech Stack). `package-lock.json` committed.
- Settings and defaults exactly as spec §8: `enable` true, `exclude` [], `mainDecks` [], `interpreter` "", `liveThresholdSeconds` 2, `maxSyncMB` 20, `memoryMB` 2048, `ignore` [].
- External decks never committed; integration fixtures are copies of torture decks made in a temp folder.
- Branch `m2b`; commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; code edits with the Edit tool.
- Python tests: `.venv/Scripts/python -m pytest`. Extension unit tests: `npm test` in `editors/vscode`. Integration: `npm run test:vscode`.

## Review Focus

1. A deck larger than `maxSyncMB` (the 170 MB Yaris main) opened in a tab: VS Code may never send it to extensions, so the client must notice the tab and send `deckcheck/check` (Task 4 `largeFileFromTabIsChecked`).
2. The server process is a venv or `py` launcher whose real interpreter is a child: Pause must leave no python process behind (Task 3 `killTree leaves no child`).
3. Settings changed while a check runs (e.g. `memoryMB` raised after a pause): the server restarts with the new options, never two servers at once (Task 4 `settingChangeRestartsOnce`).
4. A crash loop (server killed repeatedly): at most 5 restarts in 3 minutes, then off with one notification (Task 2 `restartPolicy` tests, Task 4 `serverKilledIsRestarted`).
5. No Python, or Python 3.10: one notification with "Select interpreter", status `deckcheck: no Python`, nothing else runs (Task 2 `meetsMinimum`, Task 4 `noPythonShowsStatus`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/deckcheck/lsp/server.py` (modify) | `deckcheck/active {uri}` sets the runner's front-of-queue model |
| `editors/vscode/package.json` | manifest: language, settings, commands, activation, scripts, pinned deps |
| `editors/vscode/tsconfig.json`, `.vscodeignore`, `README.md`, `LICENSE`, `NOTICE` | build and package metadata |
| `editors/vscode/scripts/bundle_libs.py` | fills `bundled/libs` with deckcheck + pygls (pure Python) |
| `editors/vscode/src/logic.ts` | pure decisions, no `vscode` import |
| `editors/vscode/src/process.ts` | find Python, spawn server, exit code, tree kill |
| `editors/vscode/src/extension.ts` | activation, client wiring, status bar, commands |
| `editors/vscode/test/unit/*.test.ts` | `node --test` unit tests |
| `editors/vscode/test/integration/*` | test-electron runner, suite, harm gate |
| `docs/m2b-extension.md` | stage report |

---

### Task 1: Server learns the active editor

**Files:**
- Modify: `src/deckcheck/lsp/server.py`
- Test: `tests/test_lsp_server.py`

**Interfaces:**
- Produces: notification client → server `deckcheck/active {uri}`; the server sets `runner.active` to the key of the first model of that file (spec §6 "the active editor's model first"; deferred minor from M2a).

- [ ] **Step 1: Failing test** (append to `tests/test_lsp_server.py`)

```python
async def test_active_notification_sets_the_front_of_the_queue(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "part.k")
        await published(client, uri(tmp_path / "main.k"))  # the first check ran the include scan
        client.protocol.notify("deckcheck/active", {"uri": uri(tmp_path / "part.k")})
        reply = await client.protocol.send_request_async("deckcheck/ping", {})
        active = reply["active"] if isinstance(reply, dict) else reply.active
        assert active and active.endswith("main.k")
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_lsp_server.py -k active -q` → FAIL (`KeyError`/`AttributeError: active`).

- [ ] **Step 3: Implement** in `server.py`:

```python
@server.feature("deckcheck/active")
def active(ls: DeckServer, params) -> None:
    path = _path(params["uri"] if isinstance(params, dict) else params.uri)
    if path is not None and not ls.ws._dirty:  # a lookup only: the protocol thread never scans (spec §3)
        ls.runner.active = ls.runner.key(ls.ws.models_for(path)[0])


@server.feature("deckcheck/ping")
def ping(ls: DeckServer, params) -> dict:
    return {"ok": True, "active": ls.runner.active}
```

(replace the existing `ping`). While a scan is pending, `active` stays unchanged.

- [ ] **Step 4: Run** the test → PASS; full suite `.venv/Scripts/python -m pytest -q -m "not install and not corpus"` → green.

- [ ] **Step 5: Commit** `git commit -m "M2b T1: deckcheck/active puts the active editor's model first"`

---

### Task 2: Extension scaffold and pure logic

**Files:**
- Create: `editors/vscode/package.json`, `tsconfig.json`, `.vscodeignore`, `.gitignore`, `src/logic.ts`, `test/unit/logic.test.ts`

**Interfaces:**
- Produces (`src/logic.ts`, no `vscode` import, erasable TypeScript only — no enums, so `node --test` runs it directly):
  - `meetsMinimum(versionText: string): boolean` — `"3 11"` style output of `print(*sys.version_info[:2])`.
  - `syncAllowed(sizeBytes: number, maxSyncMB: number): boolean`.
  - `class RestartPolicy { constructor(limit = 5, windowMs = 180_000); decide(exitCode: number | null, now: number): "restart" | "pause-memory" | "give-up" }`.
  - `statusText(state: string, notChecked: number): string`.
  - `excludeGlobs(deckcheckExclude: string[], filesExclude: Record<string, boolean>): string[]`.
  - `class Notifier { constructor(show: (msg: string) => void); once(cause: string, msg: string): void }`.

- [ ] **Step 1: Scaffold** `editors/vscode/package.json`:

```json
{
  "name": "deckcheck",
  "displayName": "deckcheck",
  "description": "Checks keyword decks for LS-DYNA as you edit: dangling references, duplicate ids, bad values, include problems.",
  "version": "0.1.0",
  "publisher": "deckcheck",
  "license": "Apache-2.0",
  "engines": { "vscode": "^1.91.0" },
  "categories": ["Linters"],
  "main": "./out/src/extension.js",
  "activationEvents": ["onLanguage:keyword-deck"],
  "contributes": {
    "languages": [{ "id": "keyword-deck", "aliases": ["Keyword deck (LS-DYNA)"], "extensions": [".k", ".key", ".dyn"] }],
    "configuration": {
      "title": "deckcheck",
      "properties": {
        "deckcheck.enable": { "type": "boolean", "default": true, "scope": "resource", "description": "Run deckcheck in this workspace or folder." },
        "deckcheck.exclude": { "type": "array", "items": { "type": "string" }, "default": [], "scope": "resource", "description": "Globs never checked or scanned (e.g. a giant mesh include)." },
        "deckcheck.mainDecks": { "type": "array", "items": { "type": "string" }, "default": [], "scope": "resource", "description": "Main decks, relative to the folder. Overrides detection." },
        "deckcheck.interpreter": { "type": "string", "default": "", "scope": "machine-overridable", "description": "Python 3.11+ that runs deckcheck. Empty: the Python extension's interpreter, then py/python3 on PATH." },
        "deckcheck.liveThresholdSeconds": { "type": "number", "default": 2, "description": "Models whose full check takes less than this are re-checked as you type; others on save." },
        "deckcheck.maxSyncMB": { "type": "number", "default": 20, "description": "Larger files are not sent to deckcheck; it reads them from disk and checks them on open and save." },
        "deckcheck.memoryMB": { "type": "number", "default": 2048, "description": "deckcheck pauses itself above this memory use." },
        "deckcheck.ignore": { "type": "array", "items": { "type": "string" }, "default": [], "description": "Codes left out, as the command line's --ignore." }
      }
    },
    "configurationDefaults": { "[keyword-deck]": { "editor.inlayHints.enabled": "offUnlessPressed" } },
    "commands": [
      { "command": "deckcheck.showStatus", "title": "deckcheck: Show status" },
      { "command": "deckcheck.pause", "title": "deckcheck: Pause for this workspace" },
      { "command": "deckcheck.resume", "title": "deckcheck: Resume" },
      { "command": "deckcheck.selectInterpreter", "title": "deckcheck: Select Python interpreter" }
    ]
  },
  "scripts": {
    "compile": "tsc -p .",
    "test": "node --test test/unit/",
    "bundle": "python scripts/bundle_libs.py",
    "test:vscode": "npm run compile && node out/test/integration/run.js",
    "package": "npm run bundle && npm run compile && vsce package --allow-missing-repository"
  },
  "dependencies": { "vscode-languageclient": "10.1.2", "@vscode/python-extension": "1.0.6" },
  "devDependencies": { "@types/vscode": "1.91.0", "@types/node": "24.0.0", "typescript": "6.0.3", "@vscode/test-electron": "3.1.0", "@vscode/vsce": "4.0.0" }
}
```

`tsconfig.json`: `{"compilerOptions": {"module": "commonjs", "target": "es2022", "outDir": "out", "rootDir": ".", "strict": true, "esModuleInterop": true, "skipLibCheck": true, "allowImportingTsExtensions": false}, "include": ["src", "test/integration"]}`.
`.gitignore`: `node_modules/`, `out/`, `bundled/`, `.vscode-test/`, `*.vsix`.
`.vscodeignore`: `src/**`, `test/**`, `scripts/**`, `.vscode-test/**`, `tsconfig.json`, `**/*.map`, `**/__pycache__/**`.

Check before installing: `npm view @types/node@24.0.0 time` — if 24.0.0 is not at least two weeks old, pick the newest 24.x that is; record it.
Run: `cd editors/vscode && npm install` → lockfile written, no audit-blocking errors.

- [ ] **Step 2: Failing unit tests** `test/unit/logic.test.ts`:

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { meetsMinimum, syncAllowed, RestartPolicy, statusText, excludeGlobs, Notifier } from "../../src/logic.ts";

test("meetsMinimum", () => {
  assert.equal(meetsMinimum("3 11"), true);
  assert.equal(meetsMinimum("3 12\n"), true);
  assert.equal(meetsMinimum("3 10"), false);
  assert.equal(meetsMinimum("garbage"), false);
});

test("syncAllowed", () => {
  assert.equal(syncAllowed(20 * 2 ** 20, 20), true);
  assert.equal(syncAllowed(20 * 2 ** 20 + 1, 20), false);
});

test("restartPolicy pauses on exit 75 and gives up after 5 in 3 minutes", () => {
  const p = new RestartPolicy();
  assert.equal(p.decide(75, 0), "pause-memory");
  const q = new RestartPolicy();
  for (let i = 0; i < 5; i++) assert.equal(q.decide(1, i * 1000), "restart");
  assert.equal(q.decide(1, 6000), "give-up");
  const r = new RestartPolicy();
  for (let i = 0; i < 5; i++) r.decide(1, i * 1000);
  assert.equal(r.decide(1, 200_000), "restart"); // the window moved on
});

test("statusText", () => {
  assert.equal(statusText("ok", 0), "deckcheck");
  assert.equal(statusText("ok", 2), "deckcheck: 2 not checked");
  assert.equal(statusText("checks on save", 0), "deckcheck: checks on save");
  assert.equal(statusText("paused", 0), "deckcheck: paused");
});

test("excludeGlobs merges files.exclude entries that are on", () => {
  assert.deepEqual(excludeGlobs(["mesh/**"], { "**/.git": true, "**/old": false }), ["mesh/**", "**/.git"]);
});

test("Notifier shows each cause once", () => {
  const shown: string[] = [];
  const n = new Notifier((m) => shown.push(m));
  n.once("no-python", "a"); n.once("no-python", "b"); n.once("crash", "c");
  assert.deepEqual(shown, ["a", "c"]);
});
```

- [ ] **Step 3: Run** `npm test` → FAIL (cannot find `src/logic.ts`).

- [ ] **Step 4: Implement** `src/logic.ts`:

```ts
// Pure decisions for the client (M2 spec §3, §4.1, §5.1, §8). No vscode import, so Node's test runner runs it.

export function meetsMinimum(versionText: string): boolean {
  const m = /^(\d+)\s+(\d+)/.exec(versionText.trim());
  if (!m) return false;
  const [major, minor] = [Number(m[1]), Number(m[2])];
  return major > 3 || (major === 3 && minor >= 11);
}

export function syncAllowed(sizeBytes: number, maxSyncMB: number): boolean {
  return sizeBytes <= maxSyncMB * 2 ** 20;
}

export class RestartPolicy {
  private starts: number[] = [];
  constructor(private limit = 5, private windowMs = 180_000) {}
  decide(exitCode: number | null, now: number): "restart" | "pause-memory" | "give-up" {
    if (exitCode === 75) return "pause-memory";
    this.starts = this.starts.filter((t) => now - t < this.windowMs);
    if (this.starts.length >= this.limit) return "give-up";
    this.starts.push(now);
    return "restart";
  }
}

export function statusText(state: string, notChecked: number): string {
  if (state === "ok") return notChecked ? `deckcheck: ${notChecked} not checked` : "deckcheck";
  return `deckcheck: ${state}`;
}

export function excludeGlobs(deckcheckExclude: string[], filesExclude: Record<string, boolean>): string[] {
  return [...deckcheckExclude, ...Object.entries(filesExclude).filter(([, on]) => on).map(([g]) => g)];
}

export class Notifier {
  private seen = new Set<string>();
  constructor(private show: (msg: string) => void) {}
  once(cause: string, msg: string): void {
    if (this.seen.has(cause)) return;
    this.seen.add(cause);
    this.show(msg);
  }
}
```

(`private` constructor parameters are not erasable syntax: if `node --test` rejects them, declare fields explicitly and assign in the constructor; ledger it.)

- [ ] **Step 5: Run** `npm test` → 6 pass. **Commit** (`editors/vscode` minus ignored dirs) `"M2b T2: extension scaffold and pure client logic"`.

---

### Task 3: Bundled libraries and the server process

**Files:**
- Create: `editors/vscode/scripts/bundle_libs.py`, `editors/vscode/src/process.ts`, `editors/vscode/test/unit/process.test.ts`

**Interfaces:**
- Consumes: M2a contract (exit 75, `deckcheck/ping`).
- Produces (`src/process.ts`, no `vscode` import):
  - `pythonVersionOk(exe: string, args: string[]): Promise<boolean>` — runs `exe ...args -c "import sys; print(*sys.version_info[:2])"`, 10 s timeout.
  - `spawnServer(exe: string, args: string[], libsDir: string): ChildProcess` — `exe ...args -m deckcheck.lsp`, `PYTHONPATH` = `libsDir` (prepended), stdio pipes, POSIX `detached: true`.
  - `exitCode(child: ChildProcess, waitMs = 1000): Promise<number | null>`.
  - `killTree(child: ChildProcess): Promise<void>` — Windows `taskkill /PID <pid> /T /F`; POSIX `process.kill(-pid, "SIGKILL")`.
  - `pathCandidates(platform: string): [string, string[]][]` — Windows `[["py", ["-3"]], ["python", []]]`, else `[["python3", []], ["python", []]]`.

- [ ] **Step 1: `scripts/bundle_libs.py`**

```python
"""Fill bundled/libs with deckcheck and pygls (all pure Python) so the extension runs with any Python 3.11+ and no
pip install (M2 spec §4.1, §9). Run from editors/vscode: python scripts/bundle_libs.py"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
LIBS = HERE / "bundled" / "libs"

if __name__ == "__main__":
    shutil.rmtree(LIBS, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", str(LIBS), "--no-compile",
                    f"{REPO}[lsp]"], check=True)
    for junk in LIBS.glob("*.dist-info/RECORD"):
        junk.unlink()
    print(f"bundled into {LIBS}: {sorted(p.name for p in LIBS.iterdir() if p.is_dir())}")
```

Run: `python scripts/bundle_libs.py` (system Python 3.12, not the venv). Expected: `deckcheck`, `pygls`, `lsprotocol`, `attrs`, `cattrs` (+ their dist-info) listed. If `pip install --target` pulls a compiled wheel, stop and ledger: the bundle must be pure Python.

- [ ] **Step 2: Failing tests** `test/unit/process.test.ts` (real processes; skipped if `py -3`/`python3` is missing):

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { exitCode, killTree, pathCandidates, pythonVersionOk, spawnServer } from "../../src/process.ts";

const LIBS = path.resolve(import.meta.dirname, "../../bundled/libs");
const [EXE, ARGS] = pathCandidates(process.platform)[0];

function frame(obj: unknown): string {
  const body = JSON.stringify(obj);
  return `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`;
}

function alive(pid: number): boolean {
  if (process.platform === "win32") {
    return execFileSync("tasklist", ["/FI", `PID eq ${pid}`, "/NH"]).toString().includes(String(pid));
  }
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function childPids(pid: number): number[] {
  if (process.platform !== "win32") return [];
  // wmic is gone from current Windows 11: ask CIM through PowerShell
  const out = execFileSync("powershell", ["-NoProfile", "-Command",
    `(Get-CimInstance Win32_Process -Filter "ParentProcessId=${pid}").ProcessId`]).toString();
  return out.split(/\s+/).filter((s) => /^\d+$/.test(s)).map(Number);
}

test("pythonVersionOk accepts the PATH python", async () => {
  assert.equal(await pythonVersionOk(EXE, ARGS), true);
});

test("server answers ping using only the bundled libs", async () => {
  const child = spawnServer(EXE, ARGS, LIBS);
  child.stdin!.write(frame({ jsonrpc: "2.0", id: 1, method: "initialize", params: { processId: null, rootUri: null, capabilities: {} } }));
  child.stdin!.write(frame({ jsonrpc: "2.0", method: "initialized", params: {} }));
  child.stdin!.write(frame({ jsonrpc: "2.0", id: 2, method: "deckcheck/ping", params: {} }));
  const out = await new Promise<string>((resolve) => {
    let buf = "";
    child.stdout!.on("data", (d) => { buf += d; if (buf.includes('"ok": true') || buf.includes('"ok":true')) resolve(buf); });
  });
  assert.match(out, /"ok":\s*true/);
  await killTree(child);
});

test("killTree leaves no child", async () => {
  const child = spawnServer(EXE, ARGS, LIBS);
  await new Promise((r) => setTimeout(r, 1500));
  const kids = childPids(child.pid!);
  await killTree(child);
  await new Promise((r) => setTimeout(r, 500));
  for (const pid of [child.pid!, ...kids]) assert.equal(alive(pid), false, `pid ${pid} still alive`);
});

test("exit code 75 is read when the budget is exceeded", async () => {
  const child = spawnServer(EXE, ARGS, LIBS);
  child.stdin!.write(frame({ jsonrpc: "2.0", id: 1, method: "initialize",
    params: { processId: null, rootUri: null, capabilities: {}, initializationOptions: { memoryMB: 1 } } }));
  assert.equal(await exitCode(child, 30_000), 75);
});
```

- [ ] **Step 3: Run** `npm test` → the four new tests FAIL (module not found).

- [ ] **Step 4: Implement** `src/process.ts`:

```ts
// The server process (M2 spec §3, §4.1): find a Python 3.11+, start deckcheck's server with the bundled libraries,
// read its exit code (75 = paused over the memory budget), and kill its whole tree: a venv's python.exe and the
// py launcher both start the real interpreter as a child.
import { ChildProcess, execFile, spawn } from "node:child_process";
import path from "node:path";

export function pathCandidates(platform: string): [string, string[]][] {
  return platform === "win32" ? [["py", ["-3"]], ["python", []]] : [["python3", []], ["python", []]];
}

export function pythonVersionOk(exe: string, args: string[]): Promise<boolean> {
  return new Promise((resolve) => {
    execFile(exe, [...args, "-c", "import sys; print(*sys.version_info[:2])"], { timeout: 10_000 },
      (err, stdout) => {
        if (err) return resolve(false);
        const m = /^(\d+)\s+(\d+)/.exec(stdout.trim());
        resolve(!!m && (Number(m[1]) > 3 || (Number(m[1]) === 3 && Number(m[2]) >= 11)));
      });
  });
}

export function spawnServer(exe: string, args: string[], libsDir: string): ChildProcess {
  const env = { ...process.env, PYTHONPATH: [libsDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) };
  return spawn(exe, [...args, "-m", "deckcheck.lsp"], { env, stdio: "pipe", detached: process.platform !== "win32",
    windowsHide: true });
}

export function exitCode(child: ChildProcess, waitMs = 1000): Promise<number | null> {
  if (child.exitCode !== null) return Promise.resolve(child.exitCode);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), waitMs);
    child.once("exit", (code) => { clearTimeout(timer); resolve(code); });
  });
}

export function killTree(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (child.pid === undefined || child.exitCode !== null) return resolve();
    if (process.platform === "win32") {
      execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true }, () => resolve());
    } else {
      try { process.kill(-child.pid, "SIGKILL"); } catch { /* already gone */ }
      resolve();
    }
  });
}
```

(The version check duplicates `meetsMinimum`'s rule: import `meetsMinimum` from `./logic.ts` instead and ledger the import form `node --test` accepts.)

- [ ] **Step 5: Run** `npm test` → all pass (10). **Commit** `"M2b T3: bundled libraries, server process: version check, spawn, exit code, tree kill"`.

---

### Task 4: The extension

**Files:**
- Create: `editors/vscode/src/extension.ts`, `editors/vscode/test/integration/run.ts`, `editors/vscode/test/integration/suite.ts`

**Interfaces:**
- Consumes: Task 2 logic, Task 3 process, M2a contract, Task 1 `deckcheck/active`.
- Produces: `activate(context)` returning `{ activationMs: number, client: () => LanguageClient | undefined, status: () => string }` (the test API).

- [ ] **Step 1: Integration harness** `test/integration/run.ts`:

```ts
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { runTests } from "@vscode/test-electron";

async function main() {
  const root = path.resolve(__dirname, "../../..");          // editors/vscode
  const torture = path.resolve(root, "../../tests/torture");
  const ws = fs.mkdtempSync(path.join(os.tmpdir(), "deckcheck-ws-"));
  for (const c of ["seeded_mistakes", "m1d_base"]) fs.cpSync(path.join(torture, c), path.join(ws, c), { recursive: true });
  fs.writeFileSync(path.join(ws, "part.k"), "*KEYWORD\n*PART\np\n         1         1         1\n*SECTION_SHELL\n         1\n*END\n");
  fs.writeFileSync(path.join(ws, "mat.k"), "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n");
  fs.writeFileSync(path.join(ws, "main.k"), "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n");
  const py = execFileSync(process.platform === "win32" ? "py" : "python3",
    [...(process.platform === "win32" ? ["-3"] : []), "-c", "import sys; print(sys.executable)"]).toString().trim();
  fs.mkdirSync(path.join(ws, ".vscode"));
  fs.writeFileSync(path.join(ws, ".vscode", "settings.json"), JSON.stringify({ "deckcheck.interpreter": py }));
  await runTests({ extensionDevelopmentPath: root, extensionTestsPath: path.join(__dirname, "suite"),
    launchArgs: [ws, "--disable-extensions"], extensionTestsEnv: { DECKCHECK_WS: ws } });
}
main().catch((e) => { console.error(e); process.exit(1); });
```

- [ ] **Step 2: Failing suite** `test/integration/suite.ts` — a minimal runner (no mocha):

```ts
import * as vscode from "vscode";
import path from "node:path";
import assert from "node:assert/strict";

const WS = process.env.DECKCHECK_WS!;
const ext = () => vscode.extensions.getExtension("deckcheck.deckcheck")!;

async function until<T>(f: () => T | undefined, ms = 60_000): Promise<T> {
  const end = Date.now() + ms;
  for (;;) {
    const v = f();
    if (v) return v;
    if (Date.now() > end) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 100));
  }
}

async function open(rel: string) {
  const doc = await vscode.workspace.openTextDocument(path.join(WS, rel));
  await vscode.window.showTextDocument(doc);
  return doc.uri;
}

const codes = (uri: vscode.Uri) => vscode.languages.getDiagnostics(uri).map((d) => String(d.code));

const tests: [string, () => Promise<void>][] = [
  ["squigglesOnSeededMistakes", async () => {
    const uri = await open("seeded_mistakes/main.k");
    await until(() => codes(uri).includes("DC001"));
    assert.ok(codes(uri).includes("DC002") && codes(uri).includes("DC004"));
  }],
  ["activationIsFast", async () => {
    assert.ok(ext().exports.activationMs < 100, `activation ${ext().exports.activationMs} ms`);
  }],
  ["includeOpenedAloneHasNoFalseDC001", async () => {
    const uri = await open("part.k");
    await until(() => ext().exports.status().length > 0 ? true : undefined);
    await new Promise((r) => setTimeout(r, 2000));
    assert.ok(!codes(uri).includes("DC001"));
  }],
  ["pauseStopsTheServerAndResumeRestarts", async () => {
    await vscode.commands.executeCommand("deckcheck.pause");
    await until(() => ext().exports.status() === "deckcheck: paused" || undefined);
    assert.equal(ext().exports.client(), undefined);
    await vscode.commands.executeCommand("deckcheck.resume");
    await until(() => ext().exports.client() || undefined);
  }],
  ["memoryPauseIsNotRestarted", async () => {
    await vscode.workspace.getConfiguration("deckcheck").update("memoryMB", 1, vscode.ConfigurationTarget.Workspace);
    await until(() => ext().exports.status().startsWith("deckcheck: paused") || undefined, 30_000);
    await new Promise((r) => setTimeout(r, 3000));
    assert.equal(ext().exports.client(), undefined);
    await vscode.workspace.getConfiguration("deckcheck").update("memoryMB", undefined, vscode.ConfigurationTarget.Workspace);
    await until(() => ext().exports.client() || undefined);
  }],
  ["settingChangeRestartsOnce", async () => {
    const before = ext().exports.client();
    await vscode.workspace.getConfiguration("deckcheck").update("ignore", ["DC005"], vscode.ConfigurationTarget.Workspace);
    const after = await until(() => (ext().exports.client() !== before && ext().exports.client()) || undefined);
    assert.ok(after);
    assert.equal(ext().exports.serverCount(), 1);
  }],
  ["serverKilledIsRestarted", async () => {
    const pid = ext().exports.serverPid();
    process.kill(pid);
    await until(() => (ext().exports.serverPid() && ext().exports.serverPid() !== pid) || undefined, 30_000);
  }],
];

export async function run(): Promise<void> {
  await ext().activate();
  const failed: string[] = [];
  for (const [name, fn] of tests) {
    try { await fn(); console.log(`ok   ${name}`); }
    catch (e) { failed.push(name); console.log(`FAIL ${name}: ${e}`); }
  }
  if (failed.length) throw new Error(`${failed.length} failed: ${failed.join(", ")}`);
}
```

(The test API therefore also exposes `serverPid(): number | undefined` and `serverCount(): number` — live server processes started and not yet exited.)

Run: `npm run test:vscode` → downloads VS Code into `.vscode-test/` (about 150 MB, once), FAILS (extension has no `main`).

- [ ] **Step 3: Implement** `src/extension.ts`:

```ts
// The deckcheck client (M2 spec §4.1). Thin by rule (§3): it reads no deck and parses nothing; every check runs
// in the Python server, started at below-normal priority and stopped by killing its whole process tree.
import * as vscode from "vscode";
import path from "node:path";
import fs from "node:fs/promises";
import { ChildProcess } from "node:child_process";
import { CloseAction, ErrorAction, LanguageClient, LanguageClientOptions, State } from "vscode-languageclient/node";
import { Notifier, RestartPolicy, excludeGlobs, statusText, syncAllowed } from "./logic";
import { exitCode, killTree, pathCandidates, pythonVersionOk, spawnServer } from "./process";

const DECKS = "**/*.{k,key,dyn,K,KEY,DYN}";
const DECK_FILE = /\.(k|key|dyn)$/i;
const PAUSED_KEY = "deckcheck.paused";

let client: LanguageClient | undefined;
let child: ChildProcess | undefined;
let live = 0;
let status: vscode.StatusBarItem;
let lastState = "";
let notChecked: { what: string; reasons: string[]; count: number }[] = [];
let ctx: vscode.ExtensionContext;
let notifier: Notifier;
let policy = new RestartPolicy();
let starting: Promise<void> | undefined;

function setStatus(state: string): void {
  lastState = state;
  status.text = statusText(state, notChecked.length);
  status.show();
}

async function findPython(): Promise<[string, string[]] | undefined> {
  const configured = vscode.workspace.getConfiguration("deckcheck").get<string>("interpreter", "");
  const candidates: [string, string[]][] = [];
  if (configured) candidates.push([configured, []]);
  else {
    if (vscode.extensions.getExtension("ms-python.python")) {
      try {
        const { PythonExtension } = await import("@vscode/python-extension");
        const api = await PythonExtension.api();
        const env = await api.environments.resolveEnvironment(api.environments.getActiveEnvironmentPath());
        const exe = env?.executable.uri?.fsPath;
        if (exe) candidates.push([exe, []]);
      } catch { /* no usable Python extension: fall through to PATH */ }
    }
    candidates.push(...pathCandidates(process.platform));
  }
  for (const [exe, args] of candidates) if (await pythonVersionOk(exe, args)) return [exe, args];
  return undefined;
}

function options(): object {
  const c = vscode.workspace.getConfiguration("deckcheck");
  const files = vscode.workspace.getConfiguration("files").get<Record<string, boolean>>("exclude", {});
  return { mainDecks: c.get("mainDecks"), exclude: excludeGlobs(c.get("exclude", []), files),
    liveThresholdSeconds: c.get("liveThresholdSeconds"), memoryMB: c.get("memoryMB"), ignore: c.get("ignore") };
}

async function tooBig(doc: vscode.TextDocument): Promise<boolean> {
  try {
    const max = vscode.workspace.getConfiguration("deckcheck").get<number>("maxSyncMB", 20);
    return !syncAllowed((await fs.stat(doc.uri.fsPath)).size, max);
  } catch { return false; }
}

function checkLargeTabs(): void {
  // VS Code may never hand a very large file to extensions; find it among the open tabs and let the server read it.
  for (const group of vscode.window.tabGroups.all) for (const tab of group.tabs) {
    const input = tab.input;
    if (input instanceof vscode.TabInputText && input.uri.scheme === "file" && DECK_FILE.test(input.uri.fsPath)) {
      fs.stat(input.uri.fsPath).then((st) => {
        const max = vscode.workspace.getConfiguration("deckcheck").get<number>("maxSyncMB", 20);
        if (!syncAllowed(st.size, max)) client?.sendNotification("deckcheck/check", { uri: input.uri.toString() });
      }, () => undefined);
    }
  }
}

async function start(): Promise<void> {
  if (client || starting) return starting;
  starting = (async () => {
    const cfg = vscode.workspace.getConfiguration("deckcheck");
    if (!cfg.get("enable", true) || ctx.workspaceState.get(PAUSED_KEY)) { setStatus("paused"); return; }
    const py = await findPython();
    if (!py) {
      setStatus("no Python");
      notifier.once("no-python", "deckcheck needs Python 3.11 or newer.");
      return;
    }
    const libs = ctx.asAbsolutePath(path.join("bundled", "libs"));
    const clientOptions: LanguageClientOptions = {
      documentSelector: [{ scheme: "file", language: "keyword-deck" }, { scheme: "file", pattern: DECKS }],
      initializationOptions: options(),
      synchronize: { fileEvents: vscode.workspace.createFileSystemWatcher(DECKS) },
      middleware: {
        didOpen: async (doc, next) => (await tooBig(doc)) ? undefined : next(doc),
        didChange: async (e, next) => (await tooBig(e.document)) ? undefined : next(e),
        didClose: async (doc, next) => (await tooBig(doc)) ? undefined : next(doc),
        didSave: async (doc, next) => (await tooBig(doc))
          ? client?.sendNotification("deckcheck/check", { uri: doc.uri.toString() }) : next(doc),
      },
      errorHandler: {
        error: () => ({ action: ErrorAction.Continue }),
        closed: async () => {
          const code = child ? await exitCode(child) : null;
          const decision = policy.decide(code, Date.now());
          if (decision === "restart") return { action: CloseAction.Restart, handled: true };
          await stop(false);
          if (decision === "pause-memory") {
            const mb = vscode.workspace.getConfiguration("deckcheck").get("memoryMB");
            setStatus(`paused (needs more than ${mb} MB)`);
            notifier.once("memory", `deckcheck paused: this model needs more than ${mb} MB. Raise deckcheck.memoryMB to check it.`);
          } else {
            setStatus("stopped");
            notifier.once("crash", "deckcheck stopped after repeated crashes; see the deckcheck output.");
          }
          return { action: CloseAction.DoNotRestart, handled: true };
        },
      },
    };
    const c = new LanguageClient("deckcheck", "deckcheck", async () => {
      child = spawnServer(py[0], py[1], libs);
      live += 1;
      child.once("exit", () => { live -= 1; });
      return child;
    }, clientOptions);
    c.onNotification("deckcheck/status", (p: { state: string; notChecked: typeof notChecked }) => {
      notChecked = p.notChecked ?? [];
      setStatus(p.state);
    });
    client = c;
    await c.start();
    checkLargeTabs();
    if (vscode.window.activeTextEditor) sendActive(vscode.window.activeTextEditor);
  })();
  try { await starting; } finally { starting = undefined; }
}

async function stop(alsoClient = true): Promise<void> {
  const c = client, p = child;
  client = undefined;
  child = undefined;
  if (alsoClient && c && c.state === State.Running) await c.stop(2000).catch(() => undefined);
  if (p) await killTree(p);
}

function sendActive(editor: vscode.TextEditor): void {
  client?.sendNotification("deckcheck/active", { uri: editor.document.uri.toString() });
}

async function restart(): Promise<void> {
  await stop();
  policy = new RestartPolicy();
  await start();
}

export function activate(context: vscode.ExtensionContext) {
  const t0 = performance.now();
  ctx = context;
  const out = vscode.window.createOutputChannel("deckcheck", { log: true });
  notifier = new Notifier((m) => {
    vscode.window.showWarningMessage(m, "Select interpreter", "Show output").then((choice) => {
      if (choice === "Select interpreter") vscode.commands.executeCommand("deckcheck.selectInterpreter");
      if (choice === "Show output") out.show();
    });
  });
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  status.command = "deckcheck.showStatus";
  context.subscriptions.push(out, status,
    vscode.commands.registerCommand("deckcheck.pause", async () => {
      await context.workspaceState.update(PAUSED_KEY, true);
      await stop();
      setStatus("paused");
    }),
    vscode.commands.registerCommand("deckcheck.resume", async () => {
      await context.workspaceState.update(PAUSED_KEY, false);
      await restart();
    }),
    vscode.commands.registerCommand("deckcheck.selectInterpreter", async () => {
      const picked = await vscode.window.showOpenDialog({ canSelectMany: false, title: "Python 3.11 or newer" });
      if (picked?.[0]) await vscode.workspace.getConfiguration("deckcheck").update("interpreter", picked[0].fsPath,
        vscode.ConfigurationTarget.Global);
    }),
    vscode.commands.registerCommand("deckcheck.showStatus", async () => {
      const items = [
        ...notChecked.map((n) => ({ label: `Not checked: ${n.what}`, detail: n.reasons.join("; ") })),
        { label: ctx.workspaceState.get(PAUSED_KEY) ? "Resume deckcheck" : "Pause deckcheck for this workspace" },
        { label: "Select Python interpreter" }, { label: "Show output" },
      ];
      const pick = await vscode.window.showQuickPick(items, { title: status.text });
      if (pick?.label.startsWith("Pause")) vscode.commands.executeCommand("deckcheck.pause");
      if (pick?.label.startsWith("Resume")) vscode.commands.executeCommand("deckcheck.resume");
      if (pick?.label.startsWith("Select")) vscode.commands.executeCommand("deckcheck.selectInterpreter");
      if (pick?.label === "Show output") out.show();
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("deckcheck") || e.affectsConfiguration("files.exclude")) void restart();
    }),
    vscode.window.onDidChangeActiveTextEditor((e) => e && sendActive(e)),
    vscode.window.tabGroups.onDidChangeTabs(() => checkLargeTabs()),
  );
  void start();  // never awaited: activation returns at once (spec §3)
  const activationMs = performance.now() - t0;
  return { activationMs, client: () => client, status: () => status.text, serverPid: () => child?.pid,
    serverCount: () => live };
}

export async function deactivate(): Promise<void> {
  await stop();
}
```

Implementer note:
- The `memoryMB` integration test changes the setting, which triggers `restart()`; the new server then exits 75 on initialize and the close handler pauses. Confirm the status text the test waits for begins with `deckcheck: paused`.

- [ ] **Step 4: Run** `npm run test:vscode` → all 7 integration tests print `ok`. If `activationIsFast` fails, find what activation awaits; nothing in `activate` may await.

- [ ] **Step 5: Commit** `"M2b T4: the extension: client wiring, sync limit, large tabs, status bar, pause, restart policy"`.

---

### Task 5: Package and install into a clean profile

**Files:**
- Create: `editors/vscode/README.md`, `editors/vscode/LICENSE` (copy of the repo's), `editors/vscode/NOTICE`, `editors/vscode/test/integration/clean.ts`, `editors/vscode/test/integration/clean-suite/index.ts`, `editors/vscode/test/integration/clean-suite/package.json`

**Interfaces:**
- Produces: `editors/vscode/deckcheck-0.1.0.vsix` (not committed).

- [ ] **Step 1: Metadata.** `README.md` (for the extension page): what it does, settings table (spec §8), "Not checked" status, pause, Python 3.11+ required, "for LS-DYNA" descriptive only, no affiliation with Ansys. `NOTICE`: the repo's NOTICE plus the bundled packages and licences: pygls (Apache-2.0), lsprotocol (MIT), attrs (MIT), cattrs (MIT), vscode-languageclient (MIT), @vscode/python-extension (MIT).

- [ ] **Step 2: Package.** `npm run package` → `deckcheck-0.1.0.vsix`. Expected: vsce lists `bundled/libs/deckcheck/...`, `out/src/extension.js`, `node_modules/vscode-languageclient/...`; no `src/`, `test/`, `.vscode-test/`. Record the size.

- [ ] **Step 3: Clean-profile test.** `clean.ts`: creates temp `--user-data-dir` and `--extensions-dir`, runs `code --extensions-dir <ext> --install-extension deckcheck-0.1.0.vsix`, then `runTests` with `extensionDevelopmentPath` = `clean-suite` (a do-nothing harness extension: `package.json` with `"name": "clean-harness", "publisher": "test", "engines": {"vscode": "^1.91.0"}, "main": "./index.js"`), `launchArgs: [ws, "--extensions-dir", ext, "--user-data-dir", data]`, and the same temp workspace as Task 4 with `deckcheck.interpreter` = the system Python, which has no deckcheck installed (verify first: `py -3 -c "import deckcheck"` must fail). `clean-suite/index.ts` opens `seeded_mistakes/main.k` and waits for DC001.

Run: `npm run compile && node out/test/integration/clean.js` → `ok cleanProfileSquiggles`.

- [ ] **Step 4: Commit** (metadata and harness; not the `.vsix`) `"M2b T5: package as .vsix; clean-profile install works with plain Python"`.

---

### Task 6: End-to-end harm gate and report

**Files:**
- Create: `editors/vscode/test/integration/harm.ts` (suite run with `DECKCHECK_HARM=1` and the corpus present)
- Create: `docs/m2b-extension.md`
- Modify: `docs/specs/2026-10-30-m2-vscode-design.md` (status line), `README.md` (an "In VS Code" section)

- [ ] **Step 1: Harm suite** (added to `suite.ts`'s list only when `process.env.DECKCHECK_HARM === "1"`; `run.ts` copies nothing — it opens the Yaris folder `.corpus/local/ccsa-yaris/2010-toyota-yaris-detailed-v2j` as the workspace):

```ts
async function openMs(file: string): Promise<number> {
  await vscode.commands.executeCommand("workbench.action.closeAllEditors");
  const t = performance.now();
  const doc = await vscode.workspace.openTextDocument(file);
  await vscode.window.showTextDocument(doc);
  return performance.now() - t;
}
const median = (xs: number[]) => xs.sort((a, b) => a - b)[Math.floor(xs.length / 2)];

["openTimeOnVsOff", async () => {
  for (const file of [MAIN, LARGEST_INCLUDE]) {
    await openMs(file);                                    // warm the OS file cache
    const on: number[] = [], off: number[] = [];
    for (let i = 0; i < 3; i++) {
      await vscode.commands.executeCommand("deckcheck.resume"); on.push(await openMs(file));
      await vscode.commands.executeCommand("deckcheck.pause");  off.push(await openMs(file));
    }
    await vscode.commands.executeCommand("deckcheck.resume");
    assert.ok(median(on) <= median(off) * 1.10, `${path.basename(file)}: on ${median(on)} ms, off ${median(off)} ms`);
  }
}],
["largeFileFromTabIsChecked", async () => {
  await openMs(MAIN);                                     // 170 MB: above maxSyncMB, maybe never synced
  await until(() => ext().exports.status() !== "deckcheck" ? true : undefined, 180_000);
}],
["commandRoundTripDuringYarisCheck", async () => {
  // an unmodified file doesn't save, so ask the server for the full check directly
  await ext().exports.client()!.sendNotification("deckcheck/check", { uri: vscode.Uri.file(MAIN).toString() });
  await new Promise((r) => setTimeout(r, 5000));
  const times: number[] = [];
  for (let i = 0; i < 20; i++) {
    const t = performance.now();
    await vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup");
    times.push(performance.now() - t);
  }
  assert.ok(Math.max(...times) < 100, `worst ${Math.max(...times)} ms`);
}],
```

Run (PowerShell): `$env:DECKCHECK_HARM=1; npm run test:vscode` → all pass; record every number.

- [ ] **Step 2: Report** `docs/m2b-extension.md`: what M2b delivers (manifest, settings, commands, status states), the `.vsix` size and contents, clean-profile result, harm gate numbers (activation, open on/off medians for the Yaris main and largest include, command round trip, large-file path), rulings, what M2c needs. README: "In VS Code" section (install the `.vsix` locally; Python 3.11+; settings table pointer). Spec status line: `M2b done <date>`.

- [ ] **Step 3: Full checks and commit.** `.venv/Scripts/python -m pytest -q -m "not install"`, `npm test`, `npm run test:vscode` → green.

```bash
git commit -m "M2b T6: end-to-end harm gate in VS Code; M2b report; README"
```

Before any publish, Chintan's hands-on trial of the `.vsix` from dry-run-verified instructions (standing preference); no publisher account without his yes.
