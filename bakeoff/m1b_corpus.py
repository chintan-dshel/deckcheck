"""M1b corpus run: deckcheck's reader and include resolver on every deck, each in a child process under 2 GB."""
import json
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST, TORTURE, run_one

OUT = Path("bakeoff/results/m1b_reader.jsonl")

if __name__ == "__main__":
    decks = [(p.parent.name, p) for p in sorted(TORTURE.glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(MANIFEST)]
    with open(OUT, "w", encoding="utf-8") as f:
        for name, deck in decks:
            row = {"name": name, **run_one(deck, cap_mb=2048, module="bakeoff.read_tree")}
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(name, row.get("error") or f"{len(row['files'])} files, {len(row['problems'])} problems",
                  row["peak_mb"], row.get("seconds"))
