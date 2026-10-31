// The deckcheck client (M2 spec §4.1). Thin by rule (§3): it reads no deck and parses nothing; every check runs
// in the Python server, started at below-normal priority and stopped by killing its whole process tree.
import * as vscode from "vscode";
import path from "node:path";
import fs from "node:fs/promises";
import { ChildProcess } from "node:child_process";
import { CloseAction, ErrorAction, LanguageClient, LanguageClientOptions, State } from "vscode-languageclient/node";
import { Notifier, RestartPolicy, excludeGlobs, statusText, syncAllowed } from "./logic.ts";
import { exitCode, killTree, pathCandidates, pythonVersionOk, spawnServer } from "./process.ts";

const DECKS = "**/*.{k,key,dyn,K,KEY,DYN}";
const DECK_FILE = /\.(k|key|dyn)$/i;
const PAUSED_KEY = "deckcheck.paused";

let client: LanguageClient | undefined;
let child: ChildProcess | undefined;
let live = 0;
let status: vscode.StatusBarItem;
let notChecked: { what: string; reasons: string[]; count: number }[] = [];
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

function setStatus(state: string): void {
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

function maxSyncMB(): number {
  return vscode.workspace.getConfiguration("deckcheck").get<number>("maxSyncMB", 20);
}

async function tooBig(doc: vscode.TextDocument): Promise<boolean> {
  try {
    return !syncAllowed((await fs.stat(doc.uri.fsPath)).size, maxSyncMB());
  } catch { return false; }
}

function checkLargeTabs(): void {
  // VS Code may never hand a very large file to extensions; find it among the open tabs and let the server read it.
  for (const group of vscode.window.tabGroups.all) for (const tab of group.tabs) {
    const input = tab.input;
    if (input instanceof vscode.TabInputText && input.uri.scheme === "file" && DECK_FILE.test(input.uri.fsPath)) {
      fs.stat(input.uri.fsPath).then((st) => {
        if (!syncAllowed(st.size, maxSyncMB())) client?.sendNotification("deckcheck/check", { uri: input.uri.toString() });
      }, () => undefined);
    }
  }
}

async function start(): Promise<void> {
  if (client) return;
  {
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
    c.onNotification("deckcheck/status", (p: { state: string; notChecked: typeof notChecked }) => {
      notChecked = p.notChecked ?? [];
      setStatus(p.state);
    });
    client = c;
    await c.start();
    checkLargeTabs();
    if (vscode.window.activeTextEditor) sendActive(vscode.window.activeTextEditor);
  }
}

async function stop(alsoClient = true): Promise<void> {
  const c = client, p = child;
  client = undefined;
  child = undefined;
  if (alsoClient && c && c.state === State.Running) await c.stop(2000).catch(() => undefined);
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
  notifier = new Notifier((m) => {
    void vscode.window.showWarningMessage(m, "Select interpreter", "Show output").then((choice) => {
      if (choice === "Select interpreter") void vscode.commands.executeCommand("deckcheck.selectInterpreter");
      if (choice === "Show output") out.show();
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
    vscode.commands.registerCommand("deckcheck.showStatus", async () => {
      const items = [
        ...notChecked.map((n) => ({ label: `Not checked: ${n.what}`, detail: n.reasons.join("; ") })),
        { label: ctx.workspaceState.get(PAUSED_KEY) ? "Resume deckcheck" : "Pause deckcheck for this workspace" },
        { label: "Select Python interpreter" }, { label: "Show output" },
      ];
      const pick = await vscode.window.showQuickPick(items, { title: status.text });
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
    serverCount: () => live };
}

export function deactivate(): Promise<void> {
  return serial(() => stop());
}
