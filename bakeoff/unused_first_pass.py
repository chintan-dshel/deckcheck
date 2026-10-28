"""First-pass check of dynars 'X N is defined but never referenced' warnings: does the id appear as a whole-number
token on any non-comment data line of another keyword block in the deck's folder tree? Prints counts and samples."""
import json
import random
import re
from collections import Counter
from pathlib import Path

RESULTS = Path(r"D:\AI_Projects\deckcheck\bakeoff\results\corpus_tier1.jsonl")
msg = re.compile(r"^(\w+) (-?\d+) is defined but never referenced")


def blocks(path: Path):
    kw, out = None, []
    for i, raw in enumerate(path.read_bytes().decode("latin-1").splitlines(), 1):
        if raw.startswith("*"):
            kw = raw.strip().upper()
        elif kw and not raw.startswith("$"):
            out.append((kw, i, raw))
    return out


tally, samples = Counter(), []
for line in RESULTS.read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    folder = Path(r["deck"]).parent
    files = [p for p in folder.rglob("*") if p.suffix.lower() in {".k", ".key", ".dyn", ".inc"}]
    data = [(p, kw, i, raw) for p in files for kw, i, raw in blocks(p)]
    for f in r["findings"]:
        m = msg.match(f["message"])
        if f["rule"] != "unreferenced_entities" or not m:
            continue
        kind, nid = m.group(1), m.group(2)
        tok = re.compile(rf"(?<![\w.+-]){re.escape(nid)}(?![\w.])")
        hits = [(p.name, kw, i) for p, kw, i, raw in data
                if tok.search(raw) and not (Path(f["file"]).name == p.name and i < f["line"] + 40 and i >= f["line"])
                and not kw.startswith(("*NODE", "*ELEMENT", "*DEFINE_CURVE", "*SET_", "*TITLE"))]
        tally[(kind, "id appears elsewhere" if hits else "no other use")] += 1
        if hits:
            samples.append((r["name"][11:], kind, nid, hits[:3]))

for k, v in sorted(tally.items()):
    print(v, k)
random.seed(0)
for s in random.sample(samples, min(12, len(samples))):
    print(s)
