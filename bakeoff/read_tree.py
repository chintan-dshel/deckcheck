"""Read one deck's include tree with deckcheck and write a summary JSON: python -m bakeoff.read_tree <deck> <out>."""
import json
import os
import sys
import time
from pathlib import Path

from deckcheck.includes import resolve_tree

deck, out = Path(sys.argv[1]), Path(sys.argv[2])
start = time.monotonic()
tree = resolve_tree(deck)
root = os.path.dirname(os.path.abspath(deck))


def rel(p):
    return Path(os.path.relpath(p, root)).as_posix()


out.write_text(json.dumps({
    "deck": str(deck),
    "files": [rel(f.path) for f in tree.files],
    "offsets": {rel(f.path): f.offsets for f in tree.files if any(f.offsets.values())},
    "problems": [{"kind": p.kind, "file": rel(p.file), "line": p.line, "name": p.name} for p in tree.problems],
    "blocks": sum(len(f.source.blocks) for f in tree.files),
    "cards": sum(len(b.cards) for f in tree.files for b in f.source.blocks),
    "seconds": round(time.monotonic() - start, 1),
}), encoding="utf-8")
