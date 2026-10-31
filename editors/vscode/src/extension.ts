// The deckcheck client (M2 spec §4.1). Thin by rule (§3): it reads no deck and parses nothing; every check runs
// in the Python server, started at below-normal priority and stopped by killing its whole process tree.
import * as vscode from "vscode";
import path from "node:path";
import fs from "node:fs/promises";
import { ChildProcess } from "node:child_process";
import { CloseAction, ErrorAction, LanguageClient, LanguageClientOptions, State } from "vscode-languageclient/node";
import { Notifier, RestartPolicy, Summary, SyncSizes, buttonsFor, busyMessage, checkTarget, checkingText, closeDecision,
  excludeGlobs, newlyOpened, statusText, summaryMessage, syncAllowed, unsavedUnsynced } from "./logic.ts";
import { exitCode, killTree, pathCandidates, pythonUsable, spawnServer } from "./process.ts";

const DECKS = "**/*.{k,key,dyn,K,KEY,DYN}";
const DECK_FILE = /\.(k|key|dyn)$/i;
const PAUSED_KEY = "deckcheck.paused";
// A large deck's check waits until VS Code has finished opening it: started at 2 s it overlapped the open and made
// opening the Yaris's 169 MB include ~24 % slower (median 1877 vs 1517 ms); started later, no slower (1378 vs 1568).
const LARGE_GRACE_MS = 10_000;
const largeSeen = new Set<string>();
const sizes = new SyncSizes();

let client: LanguageClient | undefined;
let child: ChildProcess | undefined;
let live = 0;
let status: vscode.StatusBarItem;
let notChecked: { what: string; reasons: string[]; count: number }[] = [];
let lastMain = "";
let ctx: vscode.ExtensionContext;
let notifier: Notifier;
let policy = new RestartPolicy();
let chain: Promise<void> = Promise.resolve();

function serial(work: () => Promise<void>): Promise<void> {
  // start, stop and restart run one after another: a settings change during a start must never leave zero or two
  // servers (it restarts with the new settings once the start in flight has finished)
  chain = chain.then(work, work);
  return chain;
}

let lastState = "";
let lastSummary: Summary | undefined;
let ticker: ReturnType<typeof setInterval> | undefined;
let progressDone: (() => void) | undefined;
let asked = "";                   // the model the engineer just asked to check: its progress gets a notification
const shown: string[] = [];       // messages shown, for the integration tests

function inform(message: string, ...buttons: string[]): Thenable<string | undefined> {
  shown.push(message);
  return vscode.window.showInformationMessage(message, ...buttons);
}

function stopProgress(): void {
  if (ticker) clearInterval(ticker);
  ticker = undefined;
  progressDone?.();
  progressDone = undefined;
}

function setStatus(state: string, summary?: Summary): void {
  if (state !== "checking") stopProgress();
  lastState = state;
  lastSummary = summary;
  status.text = statusText(state, notChecked.length, summary);
  status.show();
}

function onStatus(p: { main: string; state: string; notChecked: typeof notChecked; summary?: Summary;
                       estimate?: number; started?: number; busy?: boolean }): void {
  const name = path.basename(vscode.Uri.parse(p.main).fsPath);
  if (p.state === "checking") {
    const started = (p.started ?? Date.now() / 1000) * 1000, estimate = p.estimate ?? 0;
    if (p.busy) { void inform(busyMessage(name, (Date.now() - started) / 1000, estimate)); return; }
    lastMain = p.main;
    lastState = "checking";
    stopProgress();
    const tick = () => { status.text = checkingText(name, (Date.now() - started) / 1000, estimate); };
    tick();
    status.show();
    ticker = setInterval(tick, 1000);
    if (asked === p.main) {  // the engineer clicked: say so where they are looking, until the result arrives
      void vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
        title: `deckcheck: checking ${name} (about ${Math.round(estimate)} s). You can keep working.` },
      () => new Promise<void>((resolve) => { progressDone = resolve; }));
    }
    return;
  }
  notChecked = p.notChecked ?? [];
  lastMain = p.main;
  setStatus(p.state, p.summary);
  if (asked === p.main) asked = "";
  if (p.summary?.explicit) {
    void inform(summaryMessage(name, p.summary), "Show Problems").then((choice) => {
      if (choice) void vscode.commands.executeCommand("workbench.actions.view.problems");
    });
  }
}

async function unsavedLargeTabs(): Promise<vscode.Uri[]> {
  const dirty: vscode.Uri[] = [];
  for (const group of vscode.window.tabGroups.all) for (const tab of group.tabs) {
    const input = tab.input;
    if (tab.isDirty && input instanceof vscode.TabInputText && input.uri.scheme === "file"
        && DECK_FILE.test(input.uri.fsPath)) dirty.push(input.uri);
  }
  const tabs = await Promise.all(dirty.map(async (u) => ({ uri: u, name: path.basename(u.fsPath), dirty: true,
    bytes: await fs.stat(u.fsPath).then((s) => s.size, () => 0) })));
  const names = new Set(unsavedUnsynced(tabs, maxSyncMB()));
  return tabs.filter((t) => names.has(t.name)).map((t) => t.uri);
}

async function checkNow(): Promise<void> {
  // the model the status bar names when it asks to be checked, else the deck in front of you, never a non-deck
  const uri = checkTarget(lastState, lastMain, vscode.window.activeTextEditor?.document.uri.toString());
  if (!uri || !client) return;
  const unsaved = await unsavedLargeTabs();
  if (unsaved.length) {  // read from disk: the check would not see these edits (trial finding 8)
    const names = unsaved.map((u) => path.basename(u.fsPath)).join(", ");
    const choice = await vscode.window.showWarningMessage(
      `Unsaved changes in ${names} aren't seen by deckcheck until you save.`, "Save and check", "Check saved version");
    if (!choice) return;
    if (choice === "Save and check") for (const u of unsaved) await vscode.workspace.save(u);
  }
  asked = uri;
  void client.sendNotification("deckcheck/check", { uri });
}

async function findPython(libs: string): Promise<[string, string[]] | "broken" | undefined> {
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
  let broken = false;
  for (const [exe, args] of candidates) {
    const usable = await pythonUsable(exe, args, libs);
    if (usable === "ok") return [exe, args];
    broken ||= usable === "broken";
  }
  return broken ? "broken" : undefined;
}

function options(): object {
  const c = vscode.workspace.getConfiguration("deckcheck");
  const files = vscode.workspace.getConfiguration("files").get<Record<string, boolean>>("exclude", {});
  return { mainDecks: c.get("mainDecks"), exclude: excludeGlobs(c.get("exclude", []), files),
    liveThresholdSeconds: c.get("liveThresholdSeconds"), memoryMB: c.get("memoryMB"), ignore: c.get("ignore") };
}

function maxSyncMB(): number {
  return vscode.workspace.getConfiguration("deckcheck").get<number>("maxSyncMB", 20);
}

async function tooBig(doc: vscode.TextDocument): Promise<boolean> {
  try {
    return !syncAllowed((await fs.stat(doc.uri.fsPath)).size, maxSyncMB());
  } catch { return false; }
}

function checkLargeTabs(): void {
  // VS Code may never hand a very large file to extensions; find it among the open tabs and let the server read it,
  // once per opening, and only after a grace period so the editor finishes loading the file first.
  const open: vscode.Uri[] = [];
  for (const group of vscode.window.tabGroups.all) for (const tab of group.tabs) {
    const input = tab.input;
    if (input instanceof vscode.TabInputText && input.uri.scheme === "file" && DECK_FILE.test(input.uri.fsPath)) {
      open.push(input.uri);
    }
  }
  const fresh = new Set(newlyOpened(largeSeen, open.map((u) => u.toString())));
  for (const uri of open.filter((u) => fresh.has(u.toString()))) {
    fs.stat(uri.fsPath).then((st) => {
      if (!syncAllowed(st.size, maxSyncMB())) {
        setTimeout(() => {  // an opening: a big model answers "click to check" rather than starting a check
          if (largeSeen.has(uri.toString())) void client?.sendNotification("deckcheck/opened", { uri: uri.toString() });
        }, LARGE_GRACE_MS);  // closed before the grace ended: the engineer moved on, nothing to report
      }
    }, () => undefined);
  }
}

async function start(): Promise<void> {
  if (client) return;
  {
    const cfg = vscode.workspace.getConfiguration("deckcheck");
    if (!cfg.get("enable", true) || ctx.workspaceState.get(PAUSED_KEY)) { setStatus("paused"); return; }
    setStatus("starting");  // finding Python and starting the server takes seconds; "paused" must not linger meanwhile
    const libs = ctx.asAbsolutePath(path.join("bundled", "libs"));
    const py = await findPython(libs);
    if (py === "broken") {
      setStatus("stopped");
      notifier.once("broken", "deckcheck could not load its bundled files; reinstalling the extension should fix it.");
      return;
    }
    if (!py) {
      setStatus("no Python");
      notifier.once("no-python", "deckcheck needs Python 3.11 or newer.");
      return;
    }
    const clientOptions: LanguageClientOptions = {
      documentSelector: [{ scheme: "file", language: "keyword-deck" }, { scheme: "file", pattern: DECKS }],
      initializationOptions: options(),
      synchronize: { fileEvents: vscode.workspace.createFileSystemWatcher(DECKS) },
      middleware: {
        // one stat per document, at open; every later event awaits that same decision, so events keep their order
        didOpen: async (doc, next) => {
          const key = doc.uri.toString();
          sizes.set(key, tooBig(doc));
          return (await sizes.decision(key)) ? undefined : next(doc);
        },
        didChange: async (e, next) => (await sizes.decision(e.document.uri.toString())) ? undefined : next(e),
        didClose: async (doc, next) => {
          const key = doc.uri.toString();
          const big = await sizes.decision(key);
          sizes.forget(key);
          return big ? undefined : next(doc);
        },
        didSave: async (doc, next) => (await sizes.decision(doc.uri.toString()))
          ? client?.sendNotification("deckcheck/check", { uri: doc.uri.toString() }) : next(doc),
      },
      errorHandler: {
        error: () => ({ action: ErrorAction.Continue }),
        closed: async () => {
          const ours = child === undefined;  // stop() clears it first: a pause, restart or deactivation
          const code = child ? await exitCode(child) : null;
          const decision = closeDecision(ours, code, policy, Date.now());
          if (decision === "ours") return { action: CloseAction.DoNotRestart, handled: true };
          if (decision === "restart") return { action: CloseAction.Restart, handled: true };
          void stop(false);
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
      const p = spawnServer(py[0], py[1], libs);
      child = p;
      live += 1;
      p.once("exit", () => { live -= 1; });
      return p;
    }, clientOptions);
    c.onNotification("deckcheck/status", onStatus);
    try {
      await c.start();
    } catch {  // the server died before it answered: one message, and no half-started client left behind
      const p = child;
      child = undefined;
      if (p) await killTree(p);
      setStatus("stopped");
      notifier.once("start-failed", "deckcheck's server did not start; see the deckcheck output.");
      return;
    }
    client = c;
    if (lastState === "starting") setStatus("ok");  // running; with no deck open no status would ever replace it
    largeSeen.clear();  // a new server has checked nothing yet
    checkLargeTabs();
    if (vscode.window.activeTextEditor) sendActive(vscode.window.activeTextEditor);
  }
}

async function stop(alsoClient = true): Promise<void> {
  const c = client, p = child;
  client = undefined;
  child = undefined;
  // any client not already stopped, including one the library is restarting after a crash (state Starting)
  if (alsoClient && c && c.state !== State.Stopped) await c.stop(2000).catch(() => undefined);
  if (p) await killTree(p);
}

function sendActive(editor: vscode.TextEditor): void {
  void client?.sendNotification("deckcheck/active", { uri: editor.document.uri.toString() });
}

function restart(): Promise<void> {
  return serial(async () => {
    await stop();
    policy = new RestartPolicy();
    await start();
  });
}

export function activate(context: vscode.ExtensionContext) {
  const t0 = performance.now();
  ctx = context;
  const out = vscode.window.createOutputChannel("deckcheck", { log: true });
  notifier = new Notifier((m, cause) => {
    void vscode.window.showWarningMessage(m, ...buttonsFor(cause)).then((choice) => {
      if (choice === "Select interpreter") void vscode.commands.executeCommand("deckcheck.selectInterpreter");
      if (choice === "Show output") out.show();
      if (choice === "Raise the limit") void vscode.commands.executeCommand("workbench.action.openSettings", "deckcheck.memoryMB");
    });
  });
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
  status.command = "deckcheck.showStatus";
  context.subscriptions.push(out, status,
    vscode.commands.registerCommand("deckcheck.pause", async () => {
      await context.workspaceState.update(PAUSED_KEY, true);
      await serial(() => stop());
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
    vscode.commands.registerCommand("deckcheck.checkNow", checkNow),
    vscode.commands.registerCommand("deckcheck.showStatus", async () => {
      const items = [
        { label: "Check this model now" },
        ...notChecked.map((n) => ({ label: `Not checked: ${n.what}`, detail: n.reasons.join("; ") })),
        { label: ctx.workspaceState.get(PAUSED_KEY) ? "Resume deckcheck" : "Pause deckcheck for this workspace" },
        { label: "Select Python interpreter" }, { label: "Show output" },
      ];
      const pick = await vscode.window.showQuickPick(items, { title: status.text });
      if (pick?.label === "Check this model now") void vscode.commands.executeCommand("deckcheck.checkNow");
      if (pick?.label.startsWith("Pause")) void vscode.commands.executeCommand("deckcheck.pause");
      if (pick?.label.startsWith("Resume")) void vscode.commands.executeCommand("deckcheck.resume");
      if (pick?.label.startsWith("Select")) void vscode.commands.executeCommand("deckcheck.selectInterpreter");
      if (pick?.label === "Show output") out.show();
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("deckcheck") || e.affectsConfiguration("files.exclude")) void restart();
    }),
    vscode.window.onDidChangeActiveTextEditor((e) => e && sendActive(e)),
    vscode.window.tabGroups.onDidChangeTabs(() => checkLargeTabs()),
  );
  void serial(start);  // never awaited: activation returns at once (spec §3)
  const activationMs = performance.now() - t0;
  return { activationMs, client: () => client, status: () => status.text, serverPid: () => child?.pid,
    serverCount: () => live, lastStatusMain: () => lastMain, lastState: () => lastState,
    lastSummary: () => lastSummary, shown: () => [...shown] };
}

export function deactivate(): Promise<void> {
  return serial(() => stop());
}
