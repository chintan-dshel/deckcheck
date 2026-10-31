import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { runTests } from "@vscode/test-electron";

async function main() {
  delete process.env.ELECTRON_RUN_AS_NODE;  // set when launched from inside VS Code; the test editor would start as Node
  const root = path.resolve(__dirname, "../../..");          // editors/vscode
  const torture = path.resolve(root, "../../tests/torture");
  const ws = fs.mkdtempSync(path.join(os.tmpdir(), "deckcheck-ws-"));
  for (const c of ["seeded_mistakes", "m1d_base"]) fs.cpSync(path.join(torture, c), path.join(ws, c), { recursive: true });
  fs.writeFileSync(path.join(ws, "part.k"), "*KEYWORD\n*PART\np\n         1         1         1\n*SECTION_SHELL\n         1\n*END\n");
  fs.writeFileSync(path.join(ws, "mat.k"), "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n");
  fs.writeFileSync(path.join(ws, "main.k"), "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n");
  const py = execFileSync(process.platform === "win32" ? "py" : "python3",
    [...(process.platform === "win32" ? ["-3"] : []), "-c", "import sys; print(sys.executable)"]).toString().trim();
  fs.mkdirSync(path.join(ws, ".vscode"));
  fs.writeFileSync(path.join(ws, ".vscode", "settings.json"), JSON.stringify({ "deckcheck.interpreter": py }));
  await runTests({ extensionDevelopmentPath: root, extensionTestsPath: path.join(__dirname, "suite"),
    launchArgs: [ws, "--disable-extensions"], extensionTestsEnv: { DECKCHECK_WS: ws } });
}
main().catch((e) => { console.error(e); process.exit(1); });
