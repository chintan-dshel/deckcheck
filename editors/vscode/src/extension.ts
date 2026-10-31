// The deckcheck client (M2 spec §4.1). Thin by rule (§3): it reads no deck and parses nothing; every check runs
// in the Python server, started at below-normal priority and stopped by killing its whole process tree.
import * as vscode from "vscode";
import path from "node:path";
import fs from "node:fs/promises";
import { ChildProcess } from "node:child_process";
import { CloseAction, ErrorAction, LanguageClient, LanguageClientOptions, State } from "vscode-languageclient/node";
import { Notifier, RestartPolicy, StatusBoard, StatusParams, SyncSizes, alreadyChecking, buttonsFor, busyMessage,
  checkTarget, checkingText, closeDecision, excludeGlobs, newlyOpened, sameFile, statusText, summaryMessage,
  syncAllowed, unsavedUnsynced } from "./logic.ts";
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

// What the status bar shows: the client's own state while it has one (paused, starting, stopped, no Python), else
// the record of the active file's model on the board (backlog: the status used to name the last model announced).
const board = new StatusBoard();
let local: string | undefined = "starting";
let ticker: ReturnType<typeof setInterval> | undefined;
const progress = new Map<string, () => void>();  // a clicked model's progress notification, closed by its result
let askedAt = 0;                  // when the engineer last clicked: the check that starts next gets a notification
const shown: string[] = [];       // messages shown, for the integration tests
let progressShown = 0;            // progress notifications shown, for the integration tests

const nameOf = (uri: string) => path.basename(vscode.Uri.parse(uri).fsPath);

function inform(message: string, ...buttons: string[]): Thenable<string | undefined> {
  shown.push(message);
  return vscode.window.showInformationMessage(message, ...buttons);
}

function render(): void {
  const m = board.current();
  if (local !== undefined) status.text = statusText(local, 0);
  else if (!m) status.text = "deckcheck";
  else if (m.state === "checking") status.text = checkingText(nameOf(m.main), (Date.now() - (m.since ?? 0)) / 1000, m.estimate ?? 0);
  else status.text = statusText(m.state, m.notChecked.length, m.summary);
  status.show();
  if (board.anyChecking() && !ticker) ticker = setInterval(render, 1000);
  if (!board.anyChecking() && ticker) { clearInterval(ticker); ticker = undefined; }
}

function closeProgress(main?: string): void {
  for (const [k, done] of [...progress]) if (main === undefined || sameFile(k, main)) { done(); progress.delete(k); }
}

function setLocal(state: string | undefined): void {
  local = state;
  render();
}

function forgetModels(): void {  // a stopped or restarted server has checked nothing: no record outlives it
  board.clear();
  closeProgress();
  render();
}

function onStatus(p: StatusParams): void {
  if (p.busy) {  // a click on a model being checked: the server answers at once, nothing was queued
    void inform(busyMessage(nameOf(p.main), Date.now() / 1000 - (p.started ?? Date.now() / 1000), p.estimate ?? 0));
    return;
  }
  board.update(p);
  if (p.state === "checking" && Date.now() - askedAt < 30_000) {  // clicked: say so where they look, until the result
    askedAt = 0;
    progressShown += 1;
    void vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
      title: `deckcheck: checking ${nameOf(p.main)} (about ${Math.round(p.estimate ?? 0)} s). You can keep working.` },
    () => new Promise<void>((resolve) => { progress.set(p.main, resolve); }));
  }
  if (p.state !== "checking") closeProgress(p.main);
  render();
  if (p.summary?.explicit) {
    void inform(summaryMessage(nameOf(p.main), p.summary), "Show Problems").then((choice) => {
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
  const m = board.current();
  const uri = checkTarget(m?.state ?? "", m?.main ?? "", vscode.window.activeTextEditor?.document.uri.toString());
  if (!uri || !client) return;
  if (m && alreadyChecking(m.state, m.main, uri)) {
    void inform(busyMessage(nameOf(uri), (Date.now() - (m.since ?? 0)) / 1000, m.estimate ?? 0));
    return;
  }
  const unsaved = await unsavedLargeTabs();
  if (unsaved.length) {  // read from disk: the check would not see these edits (trial finding 8)
    const names = unsaved.map((u) => path.basename(u.fsPath)).join(", ");
    const choice = await vscode.window.showWarningMessage(
      `Unsaved changes in ${names} aren't seen by deckcheck until you save.`, "Save and check", "Check saved version");
    if (!choice) return;
    if (choice === "Save and check") for (const u of unsaved) await vscode.workspace.save(u);
  }
  askedAt = Date.now();  // the clicked file may be an include; the status names its main deck
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
    if (!cfg.get("enable", true) || ctx.workspaceState.get(PAUSED_KEY)) { setLocal("paused"); return; }
    setLocal("starting");  // finding Python and starting the server takes seconds; "paused" must not linger meanwhile
    const libs = ctx.asAbsolutePath(path.join("bundled", "libs"));
    const py = await findPython(libs);
    if (py === "broken") {
      setLocal("stopped");
      notifier.once("broken", "deckcheck could not load its bundled files; reinstalling the extension should fix it.");
      return;
    }
    if (!py) {
      setLocal("no Python");
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
          ? client?.sendNotification("deckcheck/check", { uri: doc.uri.toString(), reason: "save" }) : next(doc),
      },
      errorHandler: {
        error: () => ({ action: ErrorAction.Continue }),
        closed: async () => {
          const ours = child === undefined;  // stop() clears it first: a pause, restart or deactivation
          const code = child ? await exitCode(child) : null;
          const decision = closeDecision(ours, code, policy, Date.now());
          if (decision === "ours") return { action: CloseAction.DoNotRestart, handled: true };
          if (decision === "restart") {  // a check that was running died with the server: no spinner left behind
            forgetModels();
            setLocal("starting");
            largeSeen.clear();
            return { action: CloseAction.Restart, handled: true };
          }
          void stop(false);
          if (decision === "pause-memory") {
            const mb = vscode.workspace.getConfiguration("deckcheck").get("memoryMB");
            setLocal(`paused (needs more than ${mb} MB)`);
            notifier.once("memory", `deckcheck paused: this model needs more than ${mb} MB. Raise deckcheck.memoryMB to check it.`);
          } else {
            setLocal("stopped");
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
    c.onDidChangeState((e) => {  // the library restarted a crashed server: it has checked nothing yet
      if (e.newState !== State.Running || client !== c) return;
      if (local === "starting") setLocal(undefined);
      checkLargeTabs();
      if (vscode.window.activeTextEditor) sendActive(vscode.window.activeTextEditor);
    });
    try {
      await c.start();
    } catch {  // the server died before it answered: one message, and no half-started client left behind
      const p = child;
      child = undefined;
      if (p) await killTree(p);
      setLocal("stopped");
      notifier.once("start-failed", "deckcheck's server did not start; see the deckcheck output.");
      return;
    }
    client = c;
    if (local === "starting") setLocal(undefined);  // running; with no deck open no status would ever replace it
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
  forgetModels();
}

function sendActive(editor: vscode.TextEditor): void {
  // the active file's model goes first in the server's queue, and its record is what the status bar shows
  const uri = editor.document.uri.toString();
  if (!DECK_FILE.test(editor.document.uri.fsPath) || !client) return;
  client.sendRequest<{ main: string } | null>("deckcheck/active", { uri }).then((reply) => {
    if (reply?.main) { board.setActive(reply.main); render(); }
  }, () => undefined);
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
      setLocal("paused");
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
        ...(board.current()?.notChecked ?? []).map((n) => ({ label: `Not checked: ${n.what}`, detail: n.reasons.join("; ") })),
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
    vscode.window.onDidChangeActiveTextEditor((e) => {
      // no editor: a file VS Code never hands to extensions (over 50 MB), so show the model that spoke last
      if (e) sendActive(e);
      else { board.setActive(undefined); render(); }
    }),
    vscode.window.tabGroups.onDidChangeTabs(() => checkLargeTabs()),
  );
  void serial(start);  // never awaited: activation returns at once (spec §3)
  const activationMs = performance.now() - t0;
  return { activationMs, client: () => client, status: () => status.text, serverPid: () => child?.pid,
    serverCount: () => live, lastStatusMain: () => board.lastAnnounced()?.main ?? "",
    lastState: () => local ?? board.lastAnnounced()?.state ?? "ok", lastSummary: () => board.lastAnnounced()?.summary,
    activeMain: () => board.current()?.main ?? "", shown: () => [...shown], progressShown: () => progressShown };
}

export function deactivate(): Promise<void> {
  return serial(() => stop());
}
