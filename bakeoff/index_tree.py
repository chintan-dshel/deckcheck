"""Index one deck with deckcheck and write a summary JSON: python -m bakeoff.index_tree <deck> <out>."""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from deckcheck.includes import resolve_tree
from deckcheck.index import build

deck, out = Path(sys.argv[1]), Path(sys.argv[2])
start = time.monotonic()
tree = resolve_tree(deck)
ix = build(tree)
root = os.path.dirname(os.path.abspath(deck))


def rel(p):
    return Path(os.path.relpath(p, root)).as_posix()


dangling, dups = ix.dangling(), ix.duplicates()
out.write_text(json.dumps({
    "deck": str(deck),
    "files": len(tree.files),
    "defs": {k: len(v) for k, v in sorted(ix.defs.items())},
    "refs": {k: len(v[0]) for k, v in sorted(ix.refs.items())},
    "dangling_total": len(dangling),
    "dangling": [{"kind": r.kind, "id": r.id, "file": rel(r.path), "line": r.line, "field": r.field}
                 for r in dangling[:100]],
    "duplicates_total": len(dups),
    "duplicates": [{"kind": d.kind, "id": d.id, "file": rel(d.path), "line": d.line,
                    "first": f"{rel(d.first_path)}:{d.first_line}"} for d in dups[:100]],
    "blind": sorted(ix.blind),
    "uncertain_defs": {k: sorted(v)[:5] for k, v in sorted(ix.uncertain_defs.items())},
    "uncertain_uses": {k: sorted(v)[:5] for k, v in sorted(ix.uncertain_uses.items())},
    "problems": dict(Counter(p.kind for _, p in ix.problems)),
    "problem_examples": [{"file": rel(tree.files[fi].path), "line": p.line, "kind": p.kind, "detail": p.detail}
                         for fi, p in ix.problems[:20]],
    "seconds": round(time.monotonic() - start, 1),
}), encoding="utf-8")
