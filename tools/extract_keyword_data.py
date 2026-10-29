"""Extract pydyna's keyword field database (ansys-dyna-core, MIT) into deckcheck's keywords.json.

Build-time only: run in .venv-extract. deckcheck never imports pydyna at runtime.
"""
import ast
import functools
import importlib.metadata
import json
import sys
from pathlib import Path

from ansys.dyna.core import keywords as kw
from ansys.dyna.core.lib.keyword_base import KeywordBase

LIB = Path(sys.modules[KeywordBase.__module__].__file__).parent  # ansys/dyna/core/lib


@functools.cache
def _lambdas(path: str) -> dict[int, list[ast.Lambda]]:
    out: dict[int, list[ast.Lambda]] = {}
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Lambda):
            out.setdefault(node.lineno, []).append(node)
    return out


def _source(fn) -> str | None:
    """A card's condition or length lambda as Python source. None: no function, or pydyna's library default
    (a table or series read to the end of the block). "?": the lambda could not be pinned to one expression."""
    if fn is None:
        return None
    path = Path(fn.__code__.co_filename)
    if path.is_relative_to(LIB):
        return None
    texts = {ast.unparse(n.body) for n in _lambdas(str(path)).get(fn.__code__.co_firstlineno, [])}
    return texts.pop() if len(texts) == 1 else "?"


def _default(value):
    return value if type(value) in (int, float, str) else None


def _fields(schema) -> list[dict]:
    out = []
    for item in schema:
        if hasattr(item, "offset") and hasattr(item, "width"):
            out.append({"name": item.name, "type": getattr(item.type, "__name__", str(item.type)),
                        "offset": item.offset, "width": item.width, "default": _default(item.default)})
        elif isinstance(item, tuple):
            out.extend(_fields(item))
    return out


def _card(card, option: str | None) -> dict | list[dict]:
    kind = type(card).__name__
    when = _source(getattr(card, "_active_func", None))
    base = {"option": option, "conditional": when is not None, "when": when}
    length = {"length": _source(getattr(card, "_length_func", None))}
    if kind == "OptionCardSet":
        name = card._option_spec.name
        return [c for sub in card._cards for c in _flat(_card(sub, name))]
    if kind == "Card":
        return {"kind": "card", **base, "fields": _fields(card._schema)}
    if kind == "TableCard":
        return {"kind": "table", **base, **length, "fields": _fields(card._schema)}
    if kind == "TableCardGroup":
        rows = {"length": _source(getattr(card._cards[0], "_length_func", None))}
        return {"kind": "table_group", **base, **rows,
                "cards": [c for sub in card._cards for c in _flat(_card(sub, option))]}
    if kind == "SeriesCard":
        return {"kind": "series", **base, **length, "name": card._name, "element_width": card._element_width,
                "per_card": card._fields_per_card, "type": getattr(card._type, "__name__", str(card._type))}
    if kind == "CardSet":
        # A repeating set of cards (SECTION_*, HOURGLASS, ...): its cards live in one instantiated item.
        item = card._items[0] if card._items else card._set_type(parent=card, keyword=card._keyword)
        return {"kind": "card_set", **base, **length,
                "cards": [c for sub in item._cards for c in _flat(_card(sub, option))]}
    names = {"TextCard": "text", "IncludeCard": "include"}
    return {"kind": names.get(kind, "unknown"), **base, "class": kind}


def _flat(x) -> list[dict]:
    return x if isinstance(x, list) else [x]


def _name(cls) -> str:
    sub = cls.subkeyword
    return cls.keyword if not sub or sub == cls.keyword else f"{cls.keyword}_{sub}"


def extract_class(cls) -> dict:
    inst = cls()
    if any(type(c).__name__ == "CardSet" for c in inst._cards):
        inst = cls(card_set_count=1)  # a CardSet only exposes its cards once it holds an item
    specs = list(getattr(cls, "_option_spec_list", []))
    specs += [o for c in inst._cards if type(c).__name__ == "CardSet" for o in c._option_specs]
    out = {"class": cls.__name__,
           "options": [{"name": o.name, "position": str(o._position), "title_order": o._title_order}
                       for o in specs],
           "links": {f: t.name for f, t in sorted(getattr(cls, "_link_fields", {}).items())},
           "cards": [c for card in inst._cards for c in _flat(_card(card, None))]}
    if hasattr(cls, "set_legacy_format"):
        # pydyna's before_read switches to this layout when the first card is longer than 16 characters
        # (keyword_classes/manual/element_solid.py, element_solid_ortho.py)
        legacy = cls()
        legacy.set_legacy_format()
        out["legacy"] = {"first_card_longer_than": 16,
                         "cards": [c for card in legacy._cards for c in _flat(_card(card, None))]}
    return out


def extract_all() -> dict:
    # A set: the same class can be exported under more than one name, which is not a collision.
    classes = sorted({getattr(kw, n) for n in dir(kw)
                      if isinstance(getattr(kw, n), type) and issubclass(getattr(kw, n), KeywordBase)
                      and getattr(kw, n) is not KeywordBase}, key=lambda c: c.__name__)
    keywords: dict[str, dict] = {}
    for cls in classes:
        name = _name(cls)
        if name in keywords:
            raise ValueError(f"keyword name collision: {name} from {keywords[name]['class']} and {cls.__name__}")
        keywords[name] = extract_class(cls)
    return {"source": {"package": "ansys-dyna-core", "version": importlib.metadata.version("ansys-dyna-core")},
            "keywords": dict(sorted(keywords.items()))}


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(extract_all(), sort_keys=True, separators=(",", ":")), encoding="utf-8")
