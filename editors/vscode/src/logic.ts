// Pure decisions for the client (M2 spec §3, §4.1, §5.1, §8). No vscode import, so Node's test runner runs it.

export function meetsMinimum(versionText: string): boolean {
  const m = /^(\d+)\s+(\d+)/.exec(versionText.trim());
  if (!m) return false;
  const major = Number(m[1]);
  const minor = Number(m[2]);
  return major > 3 || (major === 3 && minor >= 11);
}

export function syncAllowed(sizeBytes: number, maxSyncMB: number): boolean {
  return sizeBytes <= maxSyncMB * 2 ** 20;
}

export class RestartPolicy {
  private starts: number[] = [];
  private limit: number;
  private windowMs: number;

  constructor(limit = 5, windowMs = 180_000) {
    this.limit = limit;
    this.windowMs = windowMs;
  }

  decide(exitCode: number | null, now: number): "restart" | "pause-memory" | "give-up" {
    if (exitCode === 75) return "pause-memory";
    this.starts = this.starts.filter((t) => now - t < this.windowMs);
    if (this.starts.length >= this.limit) return "give-up";
    this.starts.push(now);
    return "restart";
  }
}

export interface Summary { files: number; mb: number; seconds: number; errors: number; warnings: number;
  explicit: boolean }

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function found(s: Summary): string {
  if (!s.errors && !s.warnings) return "";
  return [s.errors && plural(s.errors, "error"), s.warnings && plural(s.warnings, "warning")].filter(Boolean)
    .join(", ");
}

export function statusText(state: string, notChecked: number, summary?: Summary): string {
  if (state === "ok") return notChecked ? `deckcheck: ${notChecked} not checked` : "deckcheck";
  if (state === "click to check") return "deckcheck: big model, click to check";
  if (state === "save to check") return "deckcheck: edited, save to check";
  if (state === "checks on save" && summary) return `deckcheck: ${found(summary) || "no problems"} (save to re-check)`;
  return `deckcheck: ${state}`;
}

export function checkingText(name: string, elapsed: number, estimate: number): string {
  const s = Math.round(elapsed);
  const tail = s > estimate ? `${s} s (longer than estimated)` : `${s} s of about ${Math.round(estimate)} s`;
  return `$(sync~spin) deckcheck: checking ${name}, ${tail}`;
}

export function summaryMessage(name: string, s: Summary): string {
  // what was covered as well as what was found: a bare "no problems" reads as "didn't run" (trial finding 6)
  const others = s.files - 1;
  const covered = others > 0 ? `${name} and ${plural(others, "included file")}` : name;
  const what = found(s).replace(", ", " and ");
  return `deckcheck checked ${covered} (${s.mb.toFixed(s.mb < 1 ? 1 : 0)} MB) in ${Math.round(s.seconds)} s: ` +
    `${what ? `${what} found` : "no problems found"}.`;
}

export function busyMessage(name: string, elapsed: number, estimate: number): string {
  const left = Math.round(estimate - elapsed);
  return `deckcheck is already checking ${name}: ${left > 5 ? `about ${left} s left` : "nearly done"}.`;
}

export function unsavedUnsynced(tabs: { name: string; dirty: boolean; bytes: number }[], maxSyncMB: number): string[] {
  // a file too big to sync is read from disk, so its unsaved edits are not what a check sees (trial finding 8)
  return tabs.filter((t) => t.dirty && !syncAllowed(t.bytes, maxSyncMB)).map((t) => t.name);
}

export function excludeGlobs(deckcheckExclude: string[], filesExclude: Record<string, boolean>): string[] {
  return [...deckcheckExclude, ...Object.entries(filesExclude).filter(([, on]) => on).map(([g]) => g)];
}

export function closeDecision(stoppedByUs: boolean, exitCode: number | null, policy: RestartPolicy,
                              now: number): "ours" | "restart" | "pause-memory" | "give-up" {
  // a pause, a settings change or deactivation stopped the server: never restart it, never announce it
  return stoppedByUs ? "ours" : policy.decide(exitCode, now);
}

const DECK = /\.(k|key|dyn)$/i;

export function checkTarget(state: string, lastMain: string, activeUri: string | undefined): string | undefined {
  // "click to check" names a model: check that one; otherwise the deck in front of the engineer, never a non-deck
  if ((state === "click to check" || state === "checking") && lastMain) return lastMain;
  if (activeUri && DECK.test(activeUri)) return activeUri;
  return lastMain || undefined;
}

export function sameFile(a: string, b: string, platform: string = process.platform): boolean {
  // VS Code writes file:///d%3A/..., the server file:///d:/...; Windows paths also ignore case
  const norm = (u: string) => (platform === "win32" ? decodeURIComponent(u).toLowerCase() : decodeURIComponent(u));
  return norm(a) === norm(b);
}

export function alreadyChecking(state: string, lastMain: string, target: string): boolean {
  // the server reads requests between checks, so its own "already checking" would come at the end: answer here
  return state === "checking" && sameFile(target, lastMain);
}

const SYNCED: Promise<boolean> = Promise.resolve(false);

export class SyncSizes {
  // Whether a document is too big to send, decided once when it opens (one stat), not per keystroke. Every event of
  // a document awaits the same promise before passing on, and continuations of one promise run in the order they
  // were registered, so open and incremental changes reach the server in the order they happened.
  private big = new Map<string, Promise<boolean>>();

  set(uri: string, tooBig: Promise<boolean>): void {
    this.big.set(uri, tooBig);
  }

  decision(uri: string): Promise<boolean> {
    return this.big.get(uri) ?? SYNCED;
  }

  forget(uri: string): void {
    this.big.delete(uri);
  }
}

export function newlyOpened(seen: Set<string>, open: string[]): string[] {
  // VS Code fires tab events on every focus change; a large deck is asked for once per opening, because a request
  // that arrives during its check makes the server discard that check and start over (spec §3).
  for (const u of [...seen]) if (!open.includes(u)) seen.delete(u);
  const fresh = open.filter((u) => !seen.has(u));
  for (const u of fresh) seen.add(u);
  return fresh;
}

export function buttonsFor(cause: string): string[] {
  return cause === "memory" ? ["Raise the limit", "Keep paused"] : ["Select interpreter", "Show output"];
}

export class Notifier {
  private seen = new Set<string>();
  private show: (msg: string, cause: string) => void;

  constructor(show: (msg: string, cause: string) => void) {
    this.show = show;
  }

  once(cause: string, msg: string): void {
    if (this.seen.has(cause)) return;
    this.seen.add(cause);
    this.show(msg, cause);
  }
}
