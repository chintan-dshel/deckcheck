"""M2c request handlers' bodies (M2 spec §5.2-5.6): answers from the last check's index and parse, or nothing
(spec §3). A request never waits: if the worker is freeing parses, the answer is nothing."""
from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types
from pygls.uris import from_fs_path

from deckcheck.includes import _key
from deckcheck.lsp.convert import m1_column, utf16_column
from deckcheck.navigate import (MAX_OUTLINE, NavIndex, block_at, card_at, explain, explain_keyword, fields_between,
                                hit, line_text, subject)
from deckcheck.navigate import outline as outline_entries
from deckcheck.reader import SourceFile, read_file

OUTLINE_REPARSE_MB = 2  # a synced file this small is re-read from the editor's text for the outline (D1)


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


def location(ls, nav: NavIndex, loc) -> types.Location:
    text = line_text(nav.tree.files[loc.fi].source, loc.line) or ""
    disk = not ls.ws.synced(loc.path)
    return types.Location(from_fs_path(str(loc.path)), types.Range(
        types.Position(loc.line - 1, utf16_column(text, loc.start, disk)),
        types.Position(loc.line - 1, utf16_column(text, loc.end, disk))))


def _subjects(ls, path: Path, position: types.Position) -> list[tuple[View, tuple[str, int, bool]]]:
    out = []
    for v in views(ls, path):
        line = position.line + 1
        block = block_at(v.src, line)
        card = card_at(block, line) if block else None
        fields = fields_between(block, line, line, v.nav.params, v.nav.long_deck) if card else None
        f = hit(fields, m1_column(card.text, position.character, v.disk)) if fields else None
        s = subject(v.nav, v.fi, fields, f) if f else None
        if s:
            out.append((v, s))
    return out


def _unique(locations: list[types.Location]) -> list[types.Location]:
    seen, out = set(), []
    for l in locations:
        k = (l.uri, l.range.start.line, l.range.start.character)
        if k not in seen:
            seen.add(k)
            out.append(l)
    return out


def definition(ls, path: Path, position: types.Position) -> list[types.Location] | None:
    def run():
        found = [location(ls, v.nav, l) for v, (kind, id_, _) in _subjects(ls, path, position)
                 for l in v.nav.definitions(kind, id_)]
        return _unique(found) or None
    return guarded(ls, run)


def references(ls, path: Path, position: types.Position, include_declaration: bool) -> list[types.Location] | None:
    def run():
        found = []
        for v, (kind, id_, is_def) in _subjects(ls, path, position):
            # a reference's uses are the uses of the definition it resolves to (a part set id may mean the part)
            target = kind if is_def else v.nav.owner(kind, id_)
            found += [location(ls, v.nav, l) for l in v.nav.uses(target, id_)]
            if include_declaration:
                found += [location(ls, v.nav, l) for l in v.nav.definitions(target, id_)]
        return _unique(found) or None
    return guarded(ls, run)


def outline(ls, path: Path) -> list[types.DocumentSymbol]:
    def run():
        vs = views(ls, path)
        if vs:
            cached = ls.outlines.get(_key(path))
            if cached is not None and cached[0] is vs[0].src:  # a kept parse is labelled once
                return cached[1]
            src, nav, disk = vs[0].src, vs[0].nav, vs[0].disk
        else:
            text = ls.ws.source(path)
            if text is None or len(text) > OUTLINE_REPARSE_MB * 2**20:
                return []
            navs = [ls.nav[_key(m)] for m in ls.ws.models_for(path) if _key(m) in ls.nav]
            nav = navs[0] if navs else None
            src, disk = read_file(path, text), False
        got = outline_entries(src, nav.params if nav else {}, nav.long_deck if nav else False)
        if isinstance(got, int):
            r = types.Range(types.Position(0, 0), types.Position(0, 0))
            out = [types.DocumentSymbol(f"Outline off: {got:,} keywords in this file (more than {MAX_OUTLINE:,})",
                                        types.SymbolKind.Null, r, r)]
        else:
            out = []
            for e in got:
                end_text = line_text(src, e.end_line) or ""
                r = types.Range(types.Position(e.line - 1, 0),
                                types.Position(e.end_line - 1, utf16_column(end_text, len(end_text), disk)))
                sel = types.Range(types.Position(e.line - 1, 0), types.Position(e.line - 1, 0))
                out.append(types.DocumentSymbol(e.name, types.SymbolKind.Struct, r, sel, detail=e.detail or None))
        if vs:
            ls.outlines[_key(path)] = (vs[0].src, out)
        return out
    return guarded(ls, run) or []
