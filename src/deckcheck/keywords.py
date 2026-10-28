"""Keyword data extracted from pydyna (ansys-dyna-core, MIT; see NOTICE). Read-only at runtime."""
import functools
import json
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
            opts = _split_options(name[cut:], {o["name"] for o in data[key]["options"]})
            if opts is not None:
                return Resolved(key, opts, fmt)
    return None
