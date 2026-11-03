"""M1 diagnostics as LSP diagnostics (M2 spec §5.1). M1 columns count characters of the text it read; the editor
counts UTF-16 units of the text it shows. M1 decodes a file from disk as Latin-1 (one character per byte) while
VS Code decodes UTF-8 with replacement, so a disk column is mapped through that decoding; text from the editor
needs only the UTF-16 count."""
from collections.abc import Callable
from pathlib import Path

from lsprotocol import types
from pygls.uris import from_fs_path

from deckcheck.diagnostics import Report

SEVERITY = {"error": types.DiagnosticSeverity.Error, "warning": types.DiagnosticSeverity.Warning}


def utf16_column(line: str, col: int, from_disk: bool) -> int:
    prefix = line[:col]
    if from_disk:
        prefix = prefix.encode("latin-1").decode("utf-8", errors="replace")
    return len(prefix.encode("utf-16-le")) // 2


def m1_column(line: str, character: int, from_disk: bool) -> int:
    """The M1 column of an editor position: the first column whose UTF-16 position reaches it."""
    lo, hi = 0, len(line)
    while lo < hi:
        mid = (lo + hi) // 2
        if utf16_column(line, mid, from_disk) < character:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _lines(source, wanted: set[int]) -> dict[int, str]:
    """The text of only the lines that carry a finding: a dict of every line of a 5-million-card mesh would add
    hundreds of MB for one finding."""
    out = {}
    for b in source.blocks:
        if b.line in wanted:
            out[b.line] = b.text
        for c in b.cards:
            if c.line in wanted:
                out[c.line] = c.text
    return out


def _uri(path: Path) -> str:
    return from_fs_path(str(path))


def to_lsp(report: Report, synced: Callable[[Path], bool]) -> dict[str, list[types.Diagnostic]]:
    """uri -> diagnostics for every file of the report's model, empty lists included so stale ones are cleared."""
    files = {_uri(f.path): f for f in report.tree.files}
    out: dict[str, list[types.Diagnostic]] = {u: [] for u in files}
    wanted: dict[str, set[int]] = {}
    for d in report.diagnostics:
        wanted.setdefault(_uri(d.path), set()).add(d.line)
    texts: dict[str, dict[int, str]] = {}
    for d in report.diagnostics:
        uri = _uri(d.path)
        node = files.get(uri)
        if node is not None and uri not in texts:
            texts[uri] = _lines(node.source, wanted[uri])
        line = texts.get(uri, {}).get(d.line)
        disk = node is None or not synced(node.path)
        start, end = ((utf16_column(line, d.start, disk), utf16_column(line, d.end, disk)) if line is not None
                      else (d.start, d.end))
        related = [types.DiagnosticRelatedInformation(
            location=types.Location(_uri(x.path), types.Range(types.Position(x.line - 1, 0),
                                                              types.Position(x.line - 1, 0))),
            message=x.message) for x in d.related]
        out.setdefault(uri, []).append(types.Diagnostic(
            range=types.Range(types.Position(d.line - 1, start), types.Position(d.line - 1, end)),
            message=d.message, severity=SEVERITY[d.severity], code=d.code, source="deckcheck",
            related_information=related or None))
    return out


def _sig(d: types.Diagnostic) -> tuple:
    r = d.range
    return (r.start.line, r.start.character, r.end.line, r.end.character, d.code, d.severity, d.message)


def merge(per_model: dict[str, dict[str, list[types.Diagnostic]]],
          names: dict[str, str]) -> dict[str, list[types.Diagnostic]]:
    """A file in several models: a finding in all of them is shown once; one in only some names those models."""
    out: dict[str, list[types.Diagnostic]] = {}
    for uri in {u for by_uri in per_model.values() for u in by_uri}:
        models = [m for m, by_uri in per_model.items() if uri in by_uri]
        seen: dict[tuple, list[str]] = {}
        first: dict[tuple, types.Diagnostic] = {}
        for m in models:
            for d in per_model[m][uri]:
                seen.setdefault(_sig(d), []).append(m)
                first.setdefault(_sig(d), d)
        merged = []
        for sig, ms in seen.items():
            d = first[sig]
            if len(models) > 1 and len(set(ms)) < len(models):
                d = types.Diagnostic(range=d.range, message=f"{d.message} (in model {', '.join(names[m] for m in ms)})",
                                     severity=d.severity, code=d.code, source=d.source,
                                     related_information=d.related_information)
            merged.append(d)
        out[uri] = merged
    return out
