// The server process (M2 spec §3, §4.1): find a Python 3.11+, start deckcheck's server with the bundled libraries,
// read its exit code (75 = paused over the memory budget), and kill its whole tree: a venv's python.exe and the
// py launcher both start the real interpreter as a child.
import { ChildProcess, execFile, spawn } from "node:child_process";
import path from "node:path";
import { meetsMinimum } from "./logic.ts";

export function pathCandidates(platform: string): [string, string[]][] {
  return platform === "win32" ? [["py", ["-3"]], ["python", []]] : [["python3", []], ["python", []]];
}

export function pythonVersionOk(exe: string, args: string[]): Promise<boolean> {
  return new Promise((resolve) => {
    execFile(exe, [...args, "-c", "import sys; print(*sys.version_info[:2])"], { timeout: 10_000, windowsHide: true },
      (err, stdout) => resolve(!err && meetsMinimum(String(stdout))));
  });
}

export function spawnServer(exe: string, args: string[], libsDir: string): ChildProcess {
  const env = { ...process.env, PYTHONPATH: [libsDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) };
  return spawn(exe, [...args, "-m", "deckcheck.lsp"], { env, stdio: "pipe", detached: process.platform !== "win32",
    windowsHide: true });
}

export function exitCode(child: ChildProcess, waitMs = 1000): Promise<number | null> {
  if (child.exitCode !== null) return Promise.resolve(child.exitCode);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), waitMs);
    child.once("exit", (code) => { clearTimeout(timer); resolve(code); });
  });
}

export function killTree(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (child.pid === undefined || child.exitCode !== null) return resolve();
    if (process.platform === "win32") {
      execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true }, () => resolve());
    } else {
      try { process.kill(-child.pid, "SIGKILL"); } catch { /* already gone */ }
      resolve();
    }
  });
}
