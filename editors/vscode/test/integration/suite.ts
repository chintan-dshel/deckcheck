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
    await until(() => codes(uri).includes("DC001") || undefined);
    assert.ok(codes(uri).includes("DC002") && codes(uri).includes("DC004"));
  }],
  ["activationIsFast", async () => {
    assert.ok(ext().exports.activationMs < 100, `activation ${ext().exports.activationMs} ms`);
  }],
  ["includeOpenedAloneHasNoFalseDC001", async () => {
    const uri = await open("part.k");
    await until(() => ext().exports.status().length > 0 || undefined);
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
    await new Promise((r) => setTimeout(r, 2000));
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
