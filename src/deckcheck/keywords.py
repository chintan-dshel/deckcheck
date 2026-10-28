"""Keyword data extracted from pydyna (ansys-dyna-core, MIT; see NOTICE). Read-only at runtime."""
import functools
import json
from importlib import resources


@functools.cache
def load() -> dict:
    return json.loads(resources.files("deckcheck.data").joinpath("keywords.json").read_text(encoding="utf-8"))
