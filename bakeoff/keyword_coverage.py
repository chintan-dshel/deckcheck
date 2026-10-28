"""How many keyword lines in the M0 corpus resolve against the extracted data? Follows plain *INCLUDE names
found next to each file (a full include resolver comes in M1b), so coverage is a lower bound."""
import json
import sys
from collections import Counter
from pathlib import Path

from bakeoff.corpus import fetch, load_manifest
from deckcheck.keywords import resolve


def keyword_lines(root: Path) -> list[str]:
    seen, todo, out = set(), [root], []
    while todo:
        f = todo.pop()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        lines = f.read_bytes().decode("latin-1").splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("*"):
                out.append(ln)
                if ln.split("$")[0].strip().upper() in ("*INCLUDE", "*INCLUDE_TRANSFORM") and i + 1 < len(lines):
                    nxt = next((x for x in lines[i + 1:i + 4] if x.strip() and not x.startswith("$")), "")
                    todo.append(f.parent / nxt.strip())
    return out


def main(out: Path) -> None:
    decks = [(p.parent.name, p) for p in sorted(Path("tests/torture").glob("*/main.k"))]
    decks += [(e.name, fetch(e)) for e in load_manifest(Path("tests/corpus/manifest.toml"))]
    report, missing_all = {}, Counter()
    for name, root in decks:
        lines = keyword_lines(root)
        missing = Counter(ln.split("$")[0].strip().upper() for ln in lines if resolve(ln) is None)
        missing_all.update(missing)
        report[name] = {"keyword_lines": len(lines), "unresolved": sum(missing.values())}
    total = sum(r["keyword_lines"] for r in report.values())
    unresolved = sum(r["unresolved"] for r in report.values())
    out.write_text(json.dumps({"total": total, "unresolved": unresolved, "decks": report,
                               "unresolved_names": missing_all.most_common()}, indent=1), encoding="utf-8")
    print(f"{total - unresolved}/{total} keyword lines resolve; top unresolved: {missing_all.most_common(10)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
