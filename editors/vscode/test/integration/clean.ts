// Install the packaged .vsix into an empty profile and extensions folder, then check that it works with a plain
// Python that has no deckcheck installed (M2 spec §11, M2b done-criterion).
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { execFileSync, spawnSync } from "node:child_process";
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath, runTests } from "@vscode/test-electron";

async function main() {
  delete process.env.ELECTRON_RUN_AS_NODE;
  const root = path.resolve(__dirname, "../../..");
  const vsix = path.join(root, "deckcheck-0.1.0.vsix");
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "deckcheck-clean-"));
  const [extDir, dataDir, ws, harness] = ["ext", "data", "ws", "harness"].map((d) => path.join(tmp, d));
  for (const d of [extDir, dataDir, ws, harness]) fs.mkdirSync(d);

  const isWin = process.platform === "win32";
  const py = execFileSync(isWin ? "py" : "python3", [...(isWin ? ["-3"] : []), "-c", "import sys; print(sys.executable)"])
    .toString().trim();
  const plain = spawnSync(py, ["-c", "import deckcheck"]);
  if (plain.status === 0) throw new Error(`${py} has deckcheck installed; the clean test needs a Python without it`);

  const exe = await downloadAndUnzipVSCode();
  const [cli, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(exe);
  const own = cliArgs.filter((a) => !a.startsWith("--extensions-dir") && !a.startsWith("--user-data-dir"));
  const install = spawnSync(cli, [...own, `--extensions-dir=${extDir}`, `--user-data-dir=${dataDir}`,
    "--install-extension", vsix], { encoding: "utf-8", shell: isWin });
  if (install.status !== 0) throw new Error(`install failed: ${install.stdout}${install.stderr}`);

  fs.cpSync(path.resolve(root, "../../tests/torture/seeded_mistakes"), path.join(ws, "seeded_mistakes"), { recursive: true });
  fs.mkdirSync(path.join(ws, ".vscode"));
  fs.writeFileSync(path.join(ws, ".vscode", "settings.json"), JSON.stringify({ "deckcheck.interpreter": py }));
  fs.writeFileSync(path.join(harness, "package.json"),
    JSON.stringify({ name: "clean-harness", publisher: "test", version: "0.0.1", engines: { vscode: "^1.91.0" } }));

  await runTests({ vscodeExecutablePath: exe, extensionDevelopmentPath: harness,
    extensionTestsPath: path.join(__dirname, "clean-suite", "index"),
    launchArgs: [ws, `--extensions-dir=${extDir}`, `--user-data-dir=${dataDir}`], extensionTestsEnv: { DECKCHECK_WS: ws } });
}
main().catch((e) => { console.error(e); process.exit(1); });
