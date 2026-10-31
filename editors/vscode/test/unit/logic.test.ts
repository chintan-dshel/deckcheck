import { test } from "node:test";
import assert from "node:assert/strict";
import { meetsMinimum, syncAllowed, RestartPolicy, statusText, excludeGlobs, Notifier, newlyOpened } from "../../src/logic.ts";

test("newlyOpened reports a tab once, again only after it was closed", () => {
  const seen = new Set<string>();
  assert.deepEqual(newlyOpened(seen, ["a", "b"]), ["a", "b"]);
  assert.deepEqual(newlyOpened(seen, ["a", "b"]), []);   // focus changes fire tab events: no new request
  assert.deepEqual(newlyOpened(seen, ["b"]), []);        // a closed
  assert.deepEqual(newlyOpened(seen, ["a", "b"]), ["a"]); // reopened
});

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
  assert.equal(statusText("click to check", 0), "deckcheck: big model, click to check");
});

test("excludeGlobs merges files.exclude entries that are on", () => {
  assert.deepEqual(excludeGlobs(["mesh/**"], { "**/.git": true, "**/old": false }), ["mesh/**", "**/.git"]);
});

test("Notifier shows each cause once", () => {
  const shown: string[] = [];
  const n = new Notifier((m) => shown.push(m));
  n.once("no-python", "a");
  n.once("no-python", "b");
  n.once("crash", "c");
  assert.deepEqual(shown, ["a", "c"]);
});

import { checkTarget, closeDecision, SyncSizes } from "../../src/logic.ts";

test("closeDecision: a close we caused is never restarted or announced", () => {
  assert.equal(closeDecision(true, null, new RestartPolicy(), 0), "ours");
  assert.equal(closeDecision(false, 75, new RestartPolicy(), 0), "pause-memory");
  assert.equal(closeDecision(false, 1, new RestartPolicy(), 0), "restart");
});

test("checkTarget follows the model the status names, and never a non-deck file", () => {
  const big = "file:///y/combine.key", deck = "file:///w/small.k", json = "file:///w/.vscode/settings.json";
  assert.equal(checkTarget("click to check", big, deck), big);   // the status asked about the big model
  assert.equal(checkTarget("ok", big, deck), deck);              // otherwise the deck in front of you
  assert.equal(checkTarget("ok", big, json), big);               // a settings file is not a deck
  assert.equal(checkTarget("ok", "", json), undefined);
});

test("SyncSizes decides once per document and keeps its events in order", async () => {
  const s = new SyncSizes();
  let release!: (v: boolean) => void;
  s.set("u", new Promise<boolean>((r) => { release = r; }));   // the open's stat is still running
  assert.equal(s.decision("u"), s.decision("u"));              // every event awaits the same decision
  const order: string[] = [];
  const handle = async (name: string) => { if (!(await s.decision("u"))) order.push(name); };
  const all = [handle("open"), handle("change 1"), handle("change 2")];
  release(false);
  await Promise.all(all);
  assert.deepEqual(order, ["open", "change 1", "change 2"]);  // forwarded in the order they happened
  s.forget("u");
  assert.equal(await s.decision("u"), false);                  // unknown: synced
});
