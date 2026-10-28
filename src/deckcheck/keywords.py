"""Keyword data extracted from pydyna (ansys-dyna-core, MIT; see NOTICE). Read-only at runtime."""
import functools
import json
import tomllib
from dataclasses import dataclass
from importlib import resources


@functools.cache
def load() -> dict:
    return json.loads(resources.files("deckcheck.data").joinpath("keywords.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Resolved:
    name: str
    options: tuple[str, ...]
    format: str


def _split_options(rest: str, allowed: set[str]) -> tuple[str, ...] | None:
    """Split '_ID_TITLE'-style remainders into known option names, longest match first."""
    out: list[str] = []
    while rest:
        if not rest.startswith("_"):
            return None
        for opt in sorted(allowed, key=len, reverse=True):
            if rest[1:].startswith(opt) and (len(rest) == len(opt) + 1 or rest[len(opt) + 1] == "_"):
                out.append(opt)
                rest = rest[len(opt) + 1:]
                break
        else:
            return None
    return tuple(out)


def resolve(line: str) -> Resolved | None:
    text = line.split("$", 1)[0].strip()
    if not text.startswith("*"):
        return None
    head, _, tail = text[1:].partition(" ")
    fmt = tail.strip() if tail.strip() in ("+", "-") else ""
    if head.endswith(("+", "-")) and not fmt:
        head, fmt = head[:-1], head[-1]
    name = head.upper()
    data = load()["keywords"]
    for cut in range(len(name), 0, -1):
        key = name[:cut]
        if key in data and (cut == len(name) or name[cut] == "_"):
            opts = _split_options(name[cut:], options_of(key))
            if opts is not None:
                return Resolved(key, opts, fmt)
    return None


@functools.cache
def overrides() -> dict:
    return tomllib.loads(resources.files("deckcheck.data").joinpath("overrides.toml").read_text(encoding="utf-8"))


def override_targets(o: dict) -> list[str]:
    """The data keys an override applies to: one keyword, a list, or a prefix minus any excluded prefixes."""
    if "keyword" in o:
        return [o["keyword"]]
    if "keywords" in o:
        return list(o["keywords"])
    skip = tuple(o.get("exclude_prefix", []))
    return [k for k in load()["keywords"] if k.startswith(o["keyword_prefix"]) and not (skip and k.startswith(skip))]


@functools.cache
def _added_options() -> dict[str, frozenset[str]]:
    added: dict[str, set[str]] = {}
    for o in overrides()["override"]:
        if "option" in o:
            for k in override_targets(o):
                added.setdefault(k, set()).add(o["set"]["add_option"]["name"])
    return {k: frozenset(v) for k, v in added.items()}


def options_of(key: str) -> set[str]:
    """Option names a keyword accepts: pydyna's data plus evidence-backed overrides."""
    return {o["name"] for o in load()["keywords"][key]["options"]} | _added_options().get(key, frozenset())
