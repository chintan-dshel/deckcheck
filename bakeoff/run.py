"""Run the probe on decks in child processes, under a memory cap, and write one JSON line per deck."""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from bakeoff.corpus import fetch, load_manifest

TORTURE = Path("tests/torture")
MANIFEST = Path("tests/corpus/manifest.toml")


def _tree_rss(proc: psutil.Process) -> int:
    # A Windows venv python.exe is a launcher; the real interpreter is its child, so measure the whole tree.
    total = proc.memory_info().rss
    for child in proc.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


def _kill_tree(proc: psutil.Process) -> None:
    for child in proc.children(recursive=True):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    proc.kill()


def run_one(deck: Path, cap_mb: int = 4096, timeout_s: float = 1800, module: str = "bakeoff.probe") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        proc = subprocess.Popen([sys.executable, "-m", module, str(deck), str(out)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        watched, peak, start = psutil.Process(proc.pid), 0, time.monotonic()
        while proc.poll() is None:
            try:
                peak = max(peak, _tree_rss(watched))
            except psutil.NoSuchProcess:
                break
            if peak > cap_mb * 2**20 or time.monotonic() - start > timeout_s:
                _kill_tree(watched)
                proc.wait()
                why = f"exceeded memory cap {cap_mb} MB" if peak > cap_mb * 2**20 else f"timeout {timeout_s} s"
                return {"deck": str(deck), "error": why, "peak_mb": round(peak / 2**20, 1)}
            time.sleep(0.05)
        stderr = proc.stderr.read().decode("utf-8", "replace")
        if not out.exists():
            return {"deck": str(deck), "error": f"probe crashed: {stderr[-2000:]}", "peak_mb": round(peak / 2**20, 1)}
        result = json.loads(out.read_text(encoding="utf-8"))
        result["peak_mb"] = round(peak / 2**20, 1)
        return result


def _decks(torture: bool, corpus: bool, tier: int | None) -> list[tuple[str, Path]]:
    decks = [(p.parent.name, p) for p in sorted(TORTURE.glob("*/main.k"))] if torture else []
    if corpus:
        decks += [(e.name, fetch(e)) for e in load_manifest(MANIFEST) if tier is None or e.tier == tier]
    return decks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--tier", type=int, help="only corpus entries of this tier")
    ap.add_argument("--cap-mb", type=int, default=4096)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for name, deck in _decks(args.torture, args.corpus, args.tier):
            row = {"name": name, **run_one(deck, cap_mb=args.cap_mb)}
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(name, "error" if "error" in row else f"{len(row['findings'])} findings", row.get("peak_mb"))


if __name__ == "__main__":
    main()
