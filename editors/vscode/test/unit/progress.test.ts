// Trial findings 6-8 (2026-10-31): a big model's check must show it is running, end with what it covered and found,
// and say when a save is needed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buttonsFor, busyMessage, checkingText, statusText, summaryMessage, unsavedUnsynced } from "../../src/logic.ts";

const clean = { files: 4, mb: 169.4, seconds: 71.2, errors: 0, warnings: 0, explicit: true };

test("checkingText counts up against the estimate, and admits an overrun", () => {
  assert.equal(checkingText("combine.key", 23.4, 70.1), "$(sync~spin) deckcheck: checking combine.key, 23 s of about 70 s");
  assert.equal(checkingText("combine.key", 81, 70), "$(sync~spin) deckcheck: checking combine.key, 81 s (longer than estimated)");
});

test("summaryMessage names what was covered as well as what was found", () => {
  assert.equal(summaryMessage("combine.key", clean),
    "deckcheck checked combine.key and 3 included files (169 MB) in 71 s: no problems found.");
  assert.equal(summaryMessage("main.k", { ...clean, files: 1, mb: 0.004, errors: 2, warnings: 1 }),
    "deckcheck checked main.k (0.0 MB) in 71 s: 2 errors and 1 warning found.");
  assert.equal(summaryMessage("a.k", { ...clean, files: 2, errors: 1 }),
    "deckcheck checked a.k and 1 included file (169 MB) in 71 s: 1 error found.");
});

test("statusText after a big check shows the counts and how to re-check", () => {
  assert.equal(statusText("checks on save", 0, clean), "deckcheck: no problems (save to re-check)");
  assert.equal(statusText("checks on save", 2, { ...clean, errors: 3, warnings: 12 }),
    "deckcheck: 3 errors, 12 warnings (save to re-check)");
  assert.equal(statusText("save to check", 0), "deckcheck: edited, save to check");
});

test("busyMessage says the check is already running and how long is left", () => {
  assert.equal(busyMessage("combine.key", 30, 70), "deckcheck is already checking combine.key: about 40 s left.");
  assert.equal(busyMessage("combine.key", 90, 70), "deckcheck is already checking combine.key: nearly done.");
});

test("unsavedUnsynced lists edited files deckcheck reads from disk", () => {
  const tabs = [{ name: "yaris.key", dirty: true, bytes: 169e6 }, { name: "combine.key", dirty: true, bytes: 1e4 },
    { name: "wall.key", dirty: false, bytes: 30e6 }];
  assert.deepEqual(unsavedUnsynced(tabs, 20), ["yaris.key"]);
});

test("buttonsFor: a memory pause offers to raise the limit or stay paused (spec §3)", () => {
  assert.deepEqual(buttonsFor("memory"), ["Raise the limit", "Keep paused"]);
  assert.deepEqual(buttonsFor("no-python"), ["Select interpreter", "Show output"]);
});
