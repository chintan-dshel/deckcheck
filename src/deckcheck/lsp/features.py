"""M2c request handlers' bodies (M2 spec §5.2-5.6): answers from the last check's index and parse, or nothing
(spec §3). A request never waits: if the worker is freeing parses, the answer is nothing."""
from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types

from deckcheck.includes import _key
from deckcheck.lsp.convert import m1_column, utf16_column
from deckcheck.navigate import NavIndex, block_at, card_at, explain, explain_keyword, fields_between, hit
from deckcheck.reader import SourceFile


@dataclass
class View:
    nav: NavIndex
    fi: int
    src: SourceFile
    disk: bool


def views(ls, path: Path) -> list[View]:
    """Each model of the file whose last check's parse of it is still the current one."""
    out = []
    for m in ls.ws.models_for(path):
        nav = ls.nav.get(_key(m))
        fi = nav.file_index(path) if nav else None
        if fi is None:
            continue
        src = nav.tree.files[fi].source
        if ls.ws.parsed(m, path) is src:
            out.append(View(nav, fi, src, not ls.ws.synced(path)))
    return out


def guarded(ls, fn):
    if not ls.ws.reading.acquire(blocking=False):
        return None
    try:
        return fn()
    except Exception as e:  # a navigation bug must never break the session (spec §3)
        ls.window_log_message(types.LogMessageParams(types.MessageType.Error, f"deckcheck: request failed: {e!r}"))
        return None
    finally:
        ls.ws.reading.release()


def hover(ls, path: Path, position: types.Position) -> types.Hover | None:
    def run():
        vs = views(ls, path)
        if not vs:
            return None
        v, line = vs[0], position.line + 1
        block = block_at(v.src, line)
        if block is None:
            return None
        if line == block.line:
            return types.Hover(types.MarkupContent(types.MarkupKind.Markdown, explain_keyword(block)))
        card = card_at(block, line)
        fields = fields_between(block, line, line, v.nav.params, v.nav.long_deck)
        if fields is None:
            return None
        f = hit(fields, m1_column(card.text, position.character, v.disk))
        text = explain(v.nav, v.fi, fields, f)
        if text is None:
            return None
        rng = types.Range(types.Position(line - 1, utf16_column(card.text, f.start, v.disk)),
                          types.Position(line - 1, utf16_column(card.text, max(f.end, f.start), v.disk)))
        return types.Hover(types.MarkupContent(types.MarkupKind.Markdown, text), range=rng)
    return guarded(ls, run)
