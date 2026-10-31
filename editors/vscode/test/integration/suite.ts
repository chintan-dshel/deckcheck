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
  ["explicitCheckOfABigModelEndsWithASummary", async () => {
    // runs before other models are opened: the status names the model last announced (deferred to M2c)
    // trial finding 6: the click's result was one changed word; it is now a message naming coverage and findings
    await vscode.workspace.getConfiguration("deckcheck").update("liveThresholdSeconds", 0, vscode.ConfigurationTarget.Workspace);
    await until(() => ext().exports.client()?.isRunning() || undefined);
    const uri = await open("seeded_mistakes/main.k");
    await until(() => (ext().exports.lastState() === "click to check"
      && ext().exports.lastStatusMain().endsWith("seeded_mistakes/main.k")) || undefined, 30_000)
      .catch((e) => { console.log(`     waiting for click to check: state "${ext().exports.lastState()}", main "${ext().exports.lastStatusMain()}"`); throw e; });
    await vscode.commands.executeCommand("deckcheck.checkNow");
    console.log(`     before click: state "${ext().exports.lastState()}", status "${ext().exports.status()}"`);
    const msg = await until(() => ext().exports.shown().find((m: string) => m.startsWith("deckcheck checked main.k")), 30_000)
      .catch((e) => { console.log(`     at timeout: state "${ext().exports.lastState()}", status "${ext().exports.status()}", shown ${JSON.stringify(ext().exports.shown())}`); throw e; });
    console.log(`     summary: ${msg}`);
    assert.match(msg, /: 3 errors found\.$/);
    assert.ok(codes(uri).includes("DC001"));
    assert.equal(ext().exports.status(), "deckcheck: 3 errors (save to re-check)");
    await vscode.workspace.getConfiguration("deckcheck").update("liveThresholdSeconds", undefined, vscode.ConfigurationTarget.Workspace);
    await until(() => ext().exports.client()?.isRunning() || undefined);
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
  ["pauseDuringCrashRestartLeavesNoServer", async () => {
    // the library restarts a crashed server on its own; a pause in that window must still leave nothing running
    await until(() => (ext().exports.client() && ext().exports.serverPid()) || undefined);
    process.kill(ext().exports.serverPid());
    await new Promise((r) => setTimeout(r, 300));
    await vscode.commands.executeCommand("deckcheck.pause");
    await new Promise((r) => setTimeout(r, 6000));
    assert.equal(ext().exports.serverCount(), 0, `${ext().exports.serverCount()} server(s) still running`);
    await vscode.commands.executeCommand("deckcheck.resume");
    await until(() => ext().exports.client() || undefined);
  }],
  ["resumeSaysStartingAndRestoresSquigglesUnaided", async () => {
    // trial finding 5: after Resume the squiggles seemed to need a click; the status still read "paused" meanwhile
    const uri = await open("seeded_mistakes/main.k");
    await until(() => codes(uri).includes("DC001") || undefined);
    await vscode.commands.executeCommand("deckcheck.pause");
    await until(() => ext().exports.status() === "deckcheck: paused" || undefined);
    const t = Date.now();
    void vscode.commands.executeCommand("deckcheck.resume");
    await new Promise((r) => setTimeout(r, 50));
    const early = ext().exports.status();
    await until(() => codes(uri).includes("DC001") || undefined, 30_000);
    console.log(`     resume -> squiggles back after ${Date.now() - t} ms, untouched (status at 50 ms: "${early}")`);
    assert.notEqual(early, "deckcheck: paused");
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

const SMALL = process.env.DECKCHECK_SMALL ?? "";

const harmTests: [string, () => Promise<void>][] = [
  ["smallFileIdleInterleaved", async () => {
    // isolates the client's own cost per open: a standalone 1 KB deck, so no full-vehicle check is involved
    const on: number[] = [], off: number[] = [];
    await openMs(SMALL);
    for (let i = 0; i < 9; i++) {
      await vscode.commands.executeCommand("deckcheck.pause");
      off.push(await openMs(SMALL));
      await vscode.commands.executeCommand("deckcheck.resume");
      await until(() => ext().exports.client()?.isRunning() || undefined);
      await new Promise((r) => setTimeout(r, 2000));
      on.push(await openMs(SMALL));
    }
    console.log(`     open small.k interleaved: on ${median(on).toFixed(0)} ms, off ${median(off).toFixed(0)} ms` +
      ` (on ${on.map((x) => x.toFixed(0)).join(" ")}; off ${off.map((x) => x.toFixed(0)).join(" ")})`);
  }],
  ["largeFileFromTabIsChecked", async () => {
    await vscode.commands.executeCommand("deckcheck.resume");
    await until(() => ext().exports.client() || undefined);
    await openMs(LARGEST);                                   // 169 MB: never synced, found through its tab
    // a big model: opening it asks instead of checking (Chintan, 2026-10-30)
    await until(() => (ext().exports.lastStatusMain().endsWith("combine.key")
      && ext().exports.lastState() === "click to check") || undefined, 60_000);
    const t = performance.now();
    await vscode.commands.executeCommand("deckcheck.checkNow");
    await new Promise((r) => setTimeout(r, 5000));
    const progress = ext().exports.status();
    await vscode.commands.executeCommand("deckcheck.checkNow");   // the impatient second click (trial finding 6)
    await until(() => ext().exports.lastState() === "checks on save" || undefined, 300_000);
    const s = (performance.now() - t) / 1000;
    const busy = ext().exports.shown().find((m: string) => m.startsWith("deckcheck is already checking"));
    const summary = ext().exports.shown().find((m: string) => m.startsWith("deckcheck checked combine.key"));
    console.log(`     large include -> click to check -> model checked after ${s.toFixed(1)} s, a second click included`);
    console.log(`     at 5 s: "${progress}"; second click: "${busy}"; result: "${summary}"`);
    assert.ok(progress.includes("checking combine.key") && busy && summary, "progress, busy answer and summary");
    assert.ok(s < 110, `the second click restarted the check: ${s.toFixed(0)} s`);
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
    judge(`open ${path.basename(MAIN)}, deckcheck idle`, idle[MAIN], off[MAIN]);
    // interleaved pairs: judged on the median of the pair differences, not on two group medians (single opens of
    // the 169 MB file range 0.9-2.1 s either way; group medians swing by more than 10 % between identical runs)
    const diffs = idle[LARGEST].map((x, i) => x - off[LARGEST][i]);
    const d = median(diffs), base = median(off[LARGEST]);
    console.log(`     open ${path.basename(LARGEST)}, deckcheck idle, paired: median difference ${d.toFixed(0)} ms` +
      ` on ${base.toFixed(0)} ms (differences ${diffs.map((x) => x.toFixed(0)).join(" ")}; on ${idle[LARGEST].map((x) => x.toFixed(0)).join(" ")}; off ${off[LARGEST].map((x) => x.toFixed(0)).join(" ")})`);
    if (d > base * 0.10 && d >= 20) slower.push(`${path.basename(LARGEST)} idle: paired median +${d.toFixed(0)} ms`);
    await ext().exports.client()!.sendNotification("deckcheck/check", { uri: vscode.Uri.file(MAIN).toString() });
    await new Promise((r) => setTimeout(r, 5000));          // the Yaris check is reading and building
    const busy: number[] = [];
    for (let i = 0; i < 9; i++) busy.push(await openMs(LARGEST));
    // reported, not gated: a big model's check now runs only when the engineer asks for it (Chintan, 2026-10-30)
    console.log(`     open ${path.basename(LARGEST)} during a Yaris check (opt-in): on ${median(busy).toFixed(0)} ms,` +
      ` off ${median(off[LARGEST]).toFixed(0)} ms (on ${busy.map((x) => x.toFixed(0)).join(" ")})`);
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
