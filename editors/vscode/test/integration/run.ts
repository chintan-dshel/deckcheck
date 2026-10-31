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
  let workspace = ws;
  const env: Record<string, string> = { DECKCHECK_WS: ws, DECKCHECK_ONLY: process.env.DECKCHECK_ONLY ?? "" };
  if (process.env.DECKCHECK_HARM === "1") {
    // the harm gate opens the CCSA Yaris folder through a workspace file, so nothing is written into the corpus
    const yaris = path.resolve(root, "../../.corpus/local/ccsa-yaris/2010-toyota-yaris-detailed-v2j");
    workspace = path.join(ws, "harm.code-workspace");
    const small = path.join(ws, "small");                       // a standalone deck: its whole check takes ms
    fs.mkdirSync(small);
    fs.copyFileSync(path.join(torture, "m1d_base", "main.k"), path.join(small, "small.k"));
    fs.writeFileSync(workspace, JSON.stringify({ folders: [{ path: yaris }, { path: small }],
      settings: { "deckcheck.interpreter": py } }));
    Object.assign(env, { DECKCHECK_HARM: "1", DECKCHECK_YARIS: yaris, DECKCHECK_SMALL: path.join(small, "small.k") });
  }
  await runTests({ extensionDevelopmentPath: root, extensionTestsPath: path.join(__dirname, "suite"),
    launchArgs: [workspace, "--disable-extensions"], extensionTestsEnv: env });
}
main().catch((e) => { console.error(e); process.exit(1); });
