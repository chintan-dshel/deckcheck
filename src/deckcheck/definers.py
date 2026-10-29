"""Which keywords define which entity kinds (data/definers.toml, plus ICFD_PART from overrides.toml), and the
families whose unknown members make a kind uncertain (docs/m1a-keyword-data.md §4.1)."""
import functools
import tomllib
from importlib import resources

from deckcheck.keywords import layout, load, override_targets, overrides, walk_cards


@functools.cache
def _table() -> dict:
    return tomllib.loads(resources.files("deckcheck.data").joinpath("definers.toml").read_text(encoding="utf-8"))


def _fields(key: str) -> set[str]:
    return {f["name"] for c in walk_cards(layout(key)["cards"]) for f in c.get("fields", [])}


@functools.cache
def definers() -> dict[str, tuple[tuple[str, str], ...]]:
    rows = [(r, r["kind"], r["field"]) for r in _table()["definer"]]
    rows += [(o, o["set"]["defines"], o["field"]) for o in overrides()["override"] if "defines" in o["set"]]
    out: dict[str, list[tuple[str, str]]] = {}
    for row, kind, field in rows:
        for key in override_targets(row):
            if key in load()["keywords"] and field in _fields(key) and not not_definer(key):
                out.setdefault(key, []).append((kind, field))
    return {k: tuple(v) for k, v in out.items()}


def not_definer(name: str) -> bool:
    return any(name == p or (p.endswith("_") and name.startswith(p)) for p in _table()["not_definers"])


@functools.cache
def family_kind(name: str) -> str | None:
    best = None
    for fam in _table()["family"]:
        p = fam["prefix"]
        if (name == p or name.startswith(p + "_")) and (best is None or len(p) > len(best[0])):
            best = (p, fam["kind"])
    return best[1] if best else None
