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
  n.once("no-python", "a");
  n.once("no-python", "b");
  n.once("crash", "c");
  assert.deepEqual(shown, ["a", "c"]);
});
