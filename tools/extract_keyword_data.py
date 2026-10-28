"""Extract pydyna's keyword field database (ansys-dyna-core, MIT) into deckcheck's keywords.json.

Build-time only: run in .venv-extract. deckcheck never imports pydyna at runtime.
"""
import importlib.metadata
import json
import sys
from pathlib import Path

from ansys.dyna.core import keywords as kw
from ansys.dyna.core.lib.keyword_base import KeywordBase


def _fields(schema) -> list[dict]:
    out = []
    for item in schema:
        if hasattr(item, "offset") and hasattr(item, "width"):
            out.append({"name": item.name, "type": getattr(item.type, "__name__", str(item.type)),
                        "offset": item.offset, "width": item.width})
        elif isinstance(item, tuple):
            out.extend(_fields(item))
    return out


def _card(card, option: str | None) -> dict | list[dict]:
    kind = type(card).__name__
    base = {"option": option, "conditional": getattr(card, "_active_func", None) is not None}
    if kind == "OptionCardSet":
        name = card._option_spec.name
        return [c for sub in card._cards for c in _flat(_card(sub, name))]
    if kind == "Card":
        return {"kind": "card", **base, "fields": _fields(card._schema)}
    if kind == "TableCard":
        return {"kind": "table", **base, "fields": _fields(card._schema)}
    if kind == "TableCardGroup":
        return {"kind": "table_group", **base, "cards": [c for sub in card._cards for c in _flat(_card(sub, option))]}
    if kind == "SeriesCard":
        return {"kind": "series", **base, "name": card._name, "element_width": card._element_width,
                "per_card": card._fields_per_card, "type": getattr(card._type, "__name__", str(card._type))}
    names = {"CardSet": "card_set", "TextCard": "text", "IncludeCard": "include"}
    return {"kind": names.get(kind, "unknown"), **base, "class": kind}


def _flat(x) -> list[dict]:
    return x if isinstance(x, list) else [x]


def _name(cls) -> str:
    sub = cls.subkeyword
    return cls.keyword if not sub or sub == cls.keyword else f"{cls.keyword}_{sub}"


def extract_class(cls) -> dict:
    inst = cls()
    return {"class": cls.__name__,
            "options": [{"name": o.name, "position": str(o._position), "title_order": o._title_order}
                        for o in getattr(cls, "_option_spec_list", [])],
            "links": {f: t.name for f, t in sorted(getattr(cls, "_link_fields", {}).items())},
            "cards": [c for card in inst._cards for c in _flat(_card(card, None))]}


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
