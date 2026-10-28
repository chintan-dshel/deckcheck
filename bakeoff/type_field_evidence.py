"""Evidence for type-dependent references: for each CONTACT_* (surfa/surfatyp, surfb/surfbtyp) and
*INITIAL_VELOCITY_GENERATION (id/styp) card in the M0 corpus, which kinds of definition does the id match in that
deck? Tallied by type value. A light scan for evidence only (fixed 10-wide or comma fields, no MPP option blocks);
the real reader comes in M1b."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from bakeoff.keyword_coverage import keyword_lines  # noqa: F401  (same include-following rule)
from deckcheck.keywords import resolve


def files_of(root: Path) -> list[Path]:
    seen, todo = [], [root]
    while todo:
        f = todo.pop()
        if f in seen or not f.is_file():
            continue
        seen.append(f)
        lines = f.read_bytes().decode("latin-1").splitlines()
        for i, ln in enumerate(lines):
            if ln.split("$")[0].strip().upper() in ("*INCLUDE", "*INCLUDE_TRANSFORM"):
                nxt = next((x for x in lines[i + 1:i + 4] if x.strip() and not x.startswith("$")), "")
                todo.append(f.parent / nxt.strip())
    return seen


def blocks(f: Path):
    cur, cards = None, []
    for ln in f.read_bytes().decode("latin-1").splitlines():
        if ln.startswith("*"):
            if cur:
                yield cur, cards
            cur, cards = ln, []
        elif cur and not ln.startswith("$"):
            cards.append(ln)
    if cur:
        yield cur, cards


def fields(card: str, n: int) -> list[str]:
    parts = card.split(",") if "," in card else [card[i * 10:(i + 1) * 10] for i in range(n)]
    return [p.strip() for p in parts] + [""] * (n - len(parts))


def as_int(s: str) -> int | None:
    try:
        return int(float(s))
    except ValueError:
        return None


KINDS = {"SET_PART": "SET_PART", "SET_NODE": "SET_NODE", "SET_SEGMENT": "SET_SEGMENT", "SET_SHELL": "SET_SHELL",
         "SET_SOLID": "SET_SOLID", "SET_BEAM": "SET_BEAM"}


def main(out: Path) -> None:
    decks = [(p.parent.name, p) for p in sorted(Path("tests/torture").glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(Path("tests/corpus/manifest.toml"))]
    tally: dict[str, Counter] = defaultdict(Counter)
    for _, root in decks:
        defs: dict[str, set[int]] = defaultdict(set)
        uses = []
        for f in files_of(root):
            for head, cards in blocks(f):
                r = resolve(head)
                if r is None:
                    continue
                pre = sum(1 for o in r.options if o == "ID")
                if r.name.startswith("PART") and r.name in ("PART", "PART_INERTIA"):
                    for i in range(1, len(cards), 2 if r.name == "PART" else 99):
                        v = as_int(fields(cards[i], 1)[0])
                        if v:
                            defs["PART"].add(v)
                for prefix, kind in KINDS.items():
                    if r.name.startswith(prefix) and cards:
                        first = cards[1] if "TITLE" in r.options and len(cards) > 1 else cards[0]
                        v = as_int(fields(first, 1)[0])
                        if v:
                            defs[kind].add(v)
                if r.name.startswith("CONTACT_") and "MPP" not in r.options and len(cards) > pre:
                    a, b, at, bt = fields(cards[pre], 4)
                    uses += [(r.name.split("_")[0] + ".surfa", at or "0", as_int(a)),
                             (r.name.split("_")[0] + ".surfb", bt or "0", as_int(b))]
                if r.name == "INITIAL_VELOCITY_GENERATION":
                    for c in cards[0::2]:
                        i, styp = fields(c, 2)
                        uses.append(("INITIAL_VELOCITY_GENERATION.id", styp, as_int(i)))
        for where, typ, ident in uses:
            if not ident:
                tally[f"{where} typ={typ}"]["(zero/blank)"] += 1
                continue
            matched = [k for k, ids in defs.items() if abs(ident) in ids] or ["(no match)"]
            # Only an id that matches exactly one kind is evidence; ambiguous ids are counted, not attributed.
            tally[f"{where} typ={typ}"][matched[0] if len(matched) == 1 else "(ambiguous)"] += 1
    out.write_text(json.dumps({k: dict(v) for k, v in sorted(tally.items())}, indent=1), encoding="utf-8")
    for k, v in sorted(tally.items()):
        print(k, dict(v))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
