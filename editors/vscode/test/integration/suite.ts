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

// The end-to-end harm gate (spec §10.1), on the CCSA Yaris: run with DECKCHECK_HARM=1 and the corpus present.
const YARIS = process.env.DECKCHECK_YARIS ?? "";
const MAIN = path.join(YARIS, "combine.key");                       // the main deck, 10 KB
const LARGEST = path.join(YARIS, "yaris-detailed-v2j.key");         // its largest include, 169 MB

async function openMs(file: string): Promise<number> {
  await vscode.commands.executeCommand("workbench.action.closeAllEditors");
  const t = performance.now();
  await vscode.commands.executeCommand("vscode.open", vscode.Uri.file(file));  // as a user opens it; no 50 MB API limit
  return performance.now() - t;
}

const median = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

const harmTests: [string, () => Promise<void>][] = [
  ["largeFileFromTabIsChecked", async () => {
    await vscode.commands.executeCommand("deckcheck.resume");
    await until(() => ext().exports.client() || undefined);
    const t = performance.now();
    await openMs(LARGEST);                                   // 169 MB: never synced, found through its tab
    await until(() => ext().exports.lastStatusMain().endsWith("combine.key") || undefined, 300_000);
    console.log(`     large include -> model combine.key checked after ${((performance.now() - t) / 1000).toFixed(1)} s`);
  }],
  ["commandRoundTripDuringYarisCheck", async () => {
    await ext().exports.client()!.sendNotification("deckcheck/check", { uri: vscode.Uri.file(MAIN).toString() });
    await new Promise((r) => setTimeout(r, 5000));           // the full check is running
    const times: number[] = [];
    for (let i = 0; i < 20; i++) {
      const t = performance.now();
      await vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup");
      times.push(performance.now() - t);
    }
    console.log(`     command round trip during a Yaris check: worst ${Math.max(...times).toFixed(1)} ms`);
    assert.ok(Math.max(...times) < 100, `worst ${Math.max(...times)} ms`);
  }],
  ["openTimeOnVsOff", async () => {
    // Two situations, measured apart: deckcheck on but idle (each open's own check is cancelled when the next
    // measurement closes the tab before the grace period ends), and a full Yaris check running in the background.
    const slower: string[] = [];
    const judge = (label: string, on: number[], off: number[]) => {
      const [m, o] = [median(on), median(off)];
      console.log(`     ${label}: on ${m.toFixed(0)} ms, off ${o.toFixed(0)} ms` +
        ` (on ${on.map((x) => x.toFixed(0)).join(" ")}; off ${off.map((x) => x.toFixed(0)).join(" ")})`);
      // within 10 %, or under 20 ms: a 50 ms open varies by ±10 % between identical runs, far below perception
      if (m > o * 1.10 && m - o >= 20) slower.push(`${label}: on ${m.toFixed(0)} ms, off ${o.toFixed(0)} ms`);
    };
    // Off and on samples are interleaved in pairs, so drift (memory pressure after a 1 GB check, disk cache, other
    // programs) falls on both sides alike. The 169 MB include is never synced, so each resumed server stays idle.
    const off: Record<string, number[]> = { [MAIN]: [], [LARGEST]: [] };
    const idle: Record<string, number[]> = { [MAIN]: [], [LARGEST]: [] };
    const resumeIdle = async () => {
      await vscode.commands.executeCommand("deckcheck.resume");
      await until(() => ext().exports.client()?.isRunning() || undefined);
      await new Promise((r) => setTimeout(r, 2000));        // steady state: the server is up, not starting
    };
    await openMs(LARGEST);                                   // warm the OS file cache
    for (let i = 0; i < 9; i++) {
      await vscode.commands.executeCommand("deckcheck.pause");
      off[LARGEST].push(await openMs(LARGEST));
      await resumeIdle();
      idle[LARGEST].push(await openMs(LARGEST));
    }
    // The main deck: its first open checks the whole model once; measured after that check, as reopening an
    // unchanged file starts no other (a resumed server would check it again, so on and off are taken in blocks)
    await openMs(MAIN);
    await until(() => ext().exports.lastStatusMain().endsWith("combine.key") || undefined, 300_000);
    for (let i = 0; i < 9; i++) idle[MAIN].push(await openMs(MAIN));
    await vscode.commands.executeCommand("deckcheck.pause");
    for (let i = 0; i < 9; i++) off[MAIN].push(await openMs(MAIN));
    await resumeIdle();
    for (const file of [MAIN, LARGEST]) judge(`open ${path.basename(file)}, deckcheck idle`, idle[file], off[file]);
    await ext().exports.client()!.sendNotification("deckcheck/check", { uri: vscode.Uri.file(MAIN).toString() });
    await new Promise((r) => setTimeout(r, 5000));          // the Yaris check is reading and building
    const busy: number[] = [];
    for (let i = 0; i < 9; i++) busy.push(await openMs(LARGEST));
    judge(`open ${path.basename(LARGEST)} during a Yaris check`, busy, off[LARGEST]);
    assert.deepEqual(slower, []);
  }],
];

export async function run(): Promise<void> {
  await ext().activate();
  const failed: string[] = [];
  const only = process.env.DECKCHECK_ONLY;
  for (const [name, fn] of (process.env.DECKCHECK_HARM === "1" ? harmTests : tests).filter(([n]) => !only || n === only)) {
    try { await fn(); console.log(`ok   ${name}`); }
    catch (e) { failed.push(name); console.log(`FAIL ${name}: ${e}`); }
  }
  if (failed.length) throw new Error(`${failed.length} failed: ${failed.join(", ")}`);
}
