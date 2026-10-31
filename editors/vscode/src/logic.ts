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

export function statusText(state: string, notChecked: number): string {
  if (state === "ok") return notChecked ? `deckcheck: ${notChecked} not checked` : "deckcheck";
  if (state === "click to check") return "deckcheck: big model, click to check";
  return `deckcheck: ${state}`;
}

export function excludeGlobs(deckcheckExclude: string[], filesExclude: Record<string, boolean>): string[] {
  return [...deckcheckExclude, ...Object.entries(filesExclude).filter(([, on]) => on).map(([g]) => g)];
}

export function newlyOpened(seen: Set<string>, open: string[]): string[] {
  // VS Code fires tab events on every focus change; a large deck is asked for once per opening, because a request
  // that arrives during its check makes the server discard that check and start over (spec §3).
  for (const u of [...seen]) if (!open.includes(u)) seen.delete(u);
  const fresh = open.filter((u) => !seen.has(u));
  for (const u of fresh) seen.add(u);
  return fresh;
}

export class Notifier {
  private seen = new Set<string>();
  private show: (msg: string) => void;

  constructor(show: (msg: string) => void) {
    this.show = show;
  }

  once(cause: string, msg: string): void {
    if (this.seen.has(cause)) return;
    this.seen.add(cause);
    this.show(msg);
  }
}
