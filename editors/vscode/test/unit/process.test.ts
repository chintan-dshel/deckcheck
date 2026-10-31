import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { exitCode, killTree, pathCandidates, pythonVersionOk, spawnServer } from "../../src/process.ts";

const LIBS = path.resolve(import.meta.dirname, "../../bundled/libs");
const [EXE, ARGS] = pathCandidates(process.platform)[0];

function frame(obj: unknown): string {
  const body = JSON.stringify(obj);
  return `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`;
}

function alive(pid: number): boolean {
  if (process.platform === "win32") {
    return execFileSync("tasklist", ["/FI", `PID eq ${pid}`, "/NH"]).toString().includes(String(pid));
  }
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function childPids(pid: number): number[] {
  if (process.platform !== "win32") return [];
  // wmic is gone from current Windows 11: ask CIM through PowerShell
  const out = execFileSync("powershell", ["-NoProfile", "-Command",
    `(Get-CimInstance Win32_Process -Filter "ParentProcessId=${pid}").ProcessId`]).toString();
  return out.split(/\s+/).filter((s) => /^\d+$/.test(s)).map(Number);
}

test("pythonVersionOk accepts the PATH python", async () => {
  assert.equal(await pythonVersionOk(EXE, ARGS), true);
});

test("server answers ping using only the bundled libs", async () => {
  const child = spawnServer(EXE, ARGS, LIBS);
  child.stdin!.write(frame({ jsonrpc: "2.0", id: 1, method: "initialize", params: { processId: null, rootUri: null, capabilities: {} } }));
  child.stdin!.write(frame({ jsonrpc: "2.0", method: "initialized", params: {} }));
  child.stdin!.write(frame({ jsonrpc: "2.0", id: 2, method: "deckcheck/ping", params: {} }));
  const out = await new Promise<string>((resolve) => {
    let buf = "";
    child.stdout!.on("data", (d) => { buf += d; if (/"ok":\s*true/.test(buf)) resolve(buf); });
  });
  assert.match(out, /"ok":\s*true/);
  await killTree(child);
});

test("killTree leaves no child", async () => {
  const child = spawnServer(EXE, ARGS, LIBS);
  await new Promise((r) => setTimeout(r, 1500));
  const kids = childPids(child.pid!);
  await killTree(child);
  await new Promise((r) => setTimeout(r, 500));
  for (const pid of [child.pid!, ...kids]) assert.equal(alive(pid), false, `pid ${pid} still alive`);
});

test("exit code 75 is read when the budget is exceeded", async () => {
  const child = spawnServer(EXE, ARGS, LIBS);
  child.stdin!.write(frame({ jsonrpc: "2.0", id: 1, method: "initialize",
    params: { processId: null, rootUri: null, capabilities: {}, initializationOptions: { memoryMB: 1 } } }));
  assert.equal(await exitCode(child, 30_000), 75);
});

import { pythonUsable } from "../../src/process.ts";
import os from "node:os";
import fs from "node:fs";

test("pythonUsable tells a broken bundle from a usable one", async () => {
  assert.equal(await pythonUsable(EXE, ARGS, LIBS), "ok");
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), "deckcheck-empty-libs-"));
  assert.equal(await pythonUsable(EXE, ARGS, empty), "broken");   // the PATH python has no deckcheck of its own
});
