import * as vscode from "vscode";
import path from "node:path";

export async function run(): Promise<void> {
  const ext = vscode.extensions.getExtension("deckcheck.deckcheck");
  if (!ext) throw new Error("deckcheck is not installed in this profile");
  const doc = await vscode.workspace.openTextDocument(path.join(process.env.DECKCHECK_WS!, "seeded_mistakes", "main.k"));
  await vscode.window.showTextDocument(doc);
  const end = Date.now() + 60_000;
  while (!vscode.languages.getDiagnostics(doc.uri).some((d) => String(d.code) === "DC001")) {
    if (Date.now() > end) throw new Error(`no DC001 after 60 s; status: ${ext.exports?.status?.()}`);
    await new Promise((r) => setTimeout(r, 200));
  }
  console.log(`ok   cleanProfileSquiggles (activation ${ext.exports.activationMs.toFixed(1)} ms)`);
}
