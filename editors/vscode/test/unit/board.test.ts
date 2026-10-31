// The client's status, one record per model (backlog: "status follows the last model announced"; both M2b.1 state
// bugs lived in loose module variables). The status bar shows the model of the file in front of the engineer.
import { test } from "node:test";
import assert from "node:assert/strict";
import { StatusBoard } from "../../src/logic.ts";

const A = "file:///d:/w/a/main.k", B = "file:///d:/w/b/main.k";
const s = (main: string, state: string, extra = {}) => ({ main, state, notChecked: [], ...extra });

test("shows the active file's model, not the last one announced", () => {
  const b = new StatusBoard();
  b.update(s(A, "click to check"));
  b.update(s(B, "ok"));
  assert.equal(b.current()?.main, B);           // no active model known: the last announced
  b.setActive(A);
  assert.equal(b.current()?.main, A);
  assert.equal(b.current()?.state, "click to check");
});

test("model keys ignore VS Code's URI spelling on Windows", () => {
  const b = new StatusBoard("win32");
  b.update(s(A, "ok"));
  b.setActive("file:///d%3A/w/a/MAIN.k");
  assert.equal(b.current()?.main, A);
});

test("an active model with no status yet falls back to the last announced", () => {
  const b = new StatusBoard();
  b.update(s(B, "ok"));
  b.setActive(A);
  assert.equal(b.current()?.main, B);
});

test("checking keeps its start and estimate; the result replaces it", () => {
  const b = new StatusBoard();
  b.update(s(A, "checking", { started: 100, estimate: 65 }));
  assert.deepEqual([b.get(A)?.state, b.get(A)?.since, b.get(A)?.estimate], ["checking", 100_000, 65]);
  b.update(s(A, "checks on save", { summary: { files: 1, mb: 1, seconds: 2, errors: 0, warnings: 0, explicit: true } }));
  assert.equal(b.get(A)?.state, "checks on save");
  assert.equal(b.get(A)?.since, undefined);
  assert.ok(b.get(A)?.summary);
});

test("a busy reply changes nothing", () => {
  const b = new StatusBoard();
  b.update(s(A, "checking", { started: 100, estimate: 65 }));
  b.update(s(A, "checking", { started: 100, estimate: 65, busy: true }));
  assert.equal(b.get(A)?.since, 100_000);
});

test("a stop forgets every model: a new server has checked nothing", () => {
  const b = new StatusBoard();
  b.update(s(A, "checking", { started: 1, estimate: 5 }));
  b.setActive(A);
  b.clear();
  assert.equal(b.current(), undefined);
  assert.equal(b.anyChecking(), false);
});
