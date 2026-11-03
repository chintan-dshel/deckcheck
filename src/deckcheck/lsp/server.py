"""Protocol handlers (M2 spec §4.2). Each handler records what changed and asks the runner; none waits for a check
(spec §3). Results are published from the runner's thread through the event loop."""
import asyncio
import gc
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import from_fs_path, to_fs_path

from deckcheck import __version__
from deckcheck.includes import _key, _norm
from deckcheck.lsp import features
from deckcheck.lsp.__main__ import start_watchdog
from deckcheck.lsp.convert import merge, to_lsp
from deckcheck.lsp.runner import Runner
from deckcheck.lsp.workspace import Settings, Workspace, drain_index
from deckcheck.navigate import NavIndex, build_nav
from deckcheck.rules import check


class DeckServer(LanguageServer):
    ws: Workspace
    runner: Runner
    loop: asyncio.AbstractEventLoop
    results: dict[str, dict[str, list[types.Diagnostic]]]
    names: dict[str, str]
    checked_at: dict[str, float]
    edited: set[str]
    checking: dict[str, tuple[float, float]]  # model key -> (wall-clock start, estimated seconds)
    nav: dict[str, NavIndex]  # model key -> the last check's navigation index (M2c)
    outlines: dict[str, tuple]  # file key -> (the parse it was made from, its outline)


server = DeckServer("deckcheck", __version__)
# Check time per MB of model, measured: bumper 18 MB in 6 s, CCSA Yaris 161 MB in 63 s. Before a model has been
# checked, its size estimates whether it is big (checked on demand and on save, not on open).
SECONDS_PER_MB = 0.4


def _path(uri: str) -> Path | None:
    p = to_fs_path(uri)
    return _norm(Path(p)) if p else None


@dataclass
class Result:
    """What the protocol thread needs from a check; built in the worker so the report is freed there."""
    diagnostics: dict[str, list[types.Diagnostic]]
    not_checked: list[dict]
    started: float  # wall-clock time the check began: files not modified since then are what it checked
    summary: dict   # what was covered and found, shown when the engineer asked (trial finding 6)
    nav: object = None  # NavIndex, built in the worker


def _status(ls: DeckServer, main: Path, state: str, items: list[dict], **extra) -> None:
    ls.protocol.notify("deckcheck/status", {"main": from_fs_path(str(main)), "state": state, "notChecked": items,
                                            **extra})


def _estimate(ls: DeckServer, main: Path, measured: float | None) -> float:
    return measured if measured is not None else ls.ws.model_mb(main) * SECONDS_PER_MB


def _on_start(ls: DeckServer, main: Path, measured: float | None) -> None:
    ls.checking[_key(main)] = (time.time(), _estimate(ls, main, measured))
    started, estimate = ls.checking[_key(main)]
    _status(ls, main, "checking", [], estimate=estimate, started=started)


def _on_busy(ls: DeckServer, main: Path) -> None:
    """Asked again while it runs: say so, rather than start over (each click restarted a 70 s check)."""
    started, estimate = ls.checking.get(_key(main), (time.time(), 0.0))
    _status(ls, main, "checking", [], estimate=estimate, started=started, busy=True)


def _publish(ls: DeckServer, main: Path, result: Result | None, error, reason: str = "check") -> None:
    ls.checking.pop(_key(main), None)
    k = _key(main)
    previous = set(ls.results.get(k, {}))
    if error is not None or result is None:
        ls.results[k] = {u: [] for u in previous}
        ls.checked_at.pop(k, None)
        ls.nav.pop(k, None)
        state, items = "check failed", []
        ls.window_log_message(types.LogMessageParams(types.MessageType.Error, f"deckcheck: {main}: {error!r}"))
    else:
        ls.results[k] = result.diagnostics
        ls.checked_at[k] = result.started
        ls.nav[k] = result.nav
        for u in previous - set(ls.results[k]):
            ls.results[k][u] = []
        state, items = ("ok" if ls.runner.live(main) else "checks on save"), result.not_checked
    ls.names[k] = main.name
    orphaned: set[str] = set()
    for m in [m for m in ls.results if m != k and ls.ws.is_orphan(m)]:  # now included by another main deck
        orphaned |= set(ls.results.pop(m))
        ls.names.pop(m, None)
    merged = merge(ls.results, ls.names)
    main_uri = from_fs_path(str(main))
    for u in orphaned - set(ls.results[k]):
        ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=u, diagnostics=merged.get(u, [])))
    for u in sorted(ls.results[k], key=lambda u: u == main_uri):  # included files first, the main deck last
        ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=u, diagnostics=merged.get(u, [])))
    if result is None:
        _status(ls, main, state, items)
        return
    explicit = _explicit(reason, result.summary["seconds"], ls.runner.live(main))
    _status(ls, main, state, items, summary={**result.summary, "explicit": explicit})


# a save's result is told in words once its check took this long: the engineer has likely moved on by then
SAVE_REPORT_SECONDS = 10.0


def _explicit(reason: str, seconds: float, live: bool) -> bool:
    """Report a result in words: always after a click; after a save only when the check took long (a popup per save
    of a 6 s model is noise, and the status bar shows the counts)."""
    return reason == "check" or (reason == "save" and not live and seconds >= SAVE_REPORT_SECONDS)


def _check(ls: DeckServer, main: Path) -> Result:
    """Worker thread. Everything that frees or builds big structures happens here, never on the protocol thread:
    a full garbage collection over a big model's millions of objects holds the GIL for ~200 ms (measured on the
    Yaris), so collection pauses during a check and the survivors are frozen out of later scans (still freed by
    reference counting); M1's structures are acyclic. The report's index is emptied a chunk at a time."""
    gc.disable()
    try:
        started = time.time()
        report = check(main, source=ls.ws.source, cache=ls.ws.cache_for(main))
        report.diagnostics[:] = [d for d in report.diagnostics if d.code not in ls.ws.settings.ignore]
        summary = {"files": len(report.tree.files), "mb": ls.ws.model_mb(main), "seconds": time.time() - started,
                   "errors": sum(d.severity == "error" for d in report.diagnostics),
                   "warnings": sum(d.severity == "warning" for d in report.diagnostics)}
        result = Result(to_lsp(report, ls.ws.synced),
                        [{"what": n.what, "reasons": list(n.reasons), "count": n.count} for n in report.not_checked],
                        started, summary)
        result.nav = build_nav(report.index)
        drain_index(report.index)
        return result
    finally:
        _release(ls)
        gc.freeze()
        gc.enable()


def _on_demand(ls: DeckServer, main: Path) -> None:
    """A big model waits for the engineer. Its last result may no longer match the files (an outside change), so
    reopening must not count it as current."""
    ls.checked_at.pop(_key(main), None)
    _status(ls, main, "click to check", [])


def _forget(ls: DeckServer, released: list[str]) -> None:
    for k in released:
        nav = ls.nav.pop(k, None)
        for f in nav.tree.files if nav else ():
            ls.outlines.pop(_key(f.path), None)


def _release(ls: DeckServer) -> None:
    """Worker thread: a closed model's parsed files (about 1 GB for the Yaris) are freed, a chunk at a time, and
    its navigation index is forgotten."""
    released = ls.ws.release_closed()
    if released:
        ls.loop.call_soon_threadsafe(_forget, ls, released)


def _prepare(ls: DeckServer) -> None:
    ls.ws.apply_drops()
    _release(ls)
    ls.ws.ensure_scanned()


@server.feature(types.INITIALIZE)
def initialize(ls: DeckServer, params: types.InitializeParams) -> None:
    opts = params.initialization_options or {}
    folders = [Path(to_fs_path(f.uri)) for f in (params.workspace_folders or [])]
    if not folders and params.root_uri:
        folders = [Path(to_fs_path(params.root_uri))]
    settings = Settings.from_options(opts, folders[0] if folders else Path.cwd())
    start_watchdog(settings.memory_mb)
    ls.loop = asyncio.get_running_loop()
    ls.ws = Workspace(folders, settings)
    ls.results, ls.names = {}, {}
    ls.checked_at, ls.edited, ls.checking, ls.nav, ls.outlines = {}, set(), {}, {}, {}
    on_loop = ls.loop.call_soon_threadsafe
    ls.runner = Runner(models=ls.ws.models_for, check=lambda m: _check(ls, m),
                       publish=lambda m, r, e, why: on_loop(_publish, ls, m, r, e, why),
                       threshold=settings.live_threshold, prepare=lambda: _prepare(ls),
                       report_error=lambda e: ls.loop.call_soon_threadsafe(
                           ls.window_log_message, types.LogMessageParams(types.MessageType.Error,
                                                                         f"deckcheck: worker error: {e!r}")),
                       big=lambda m: ls.ws.model_mb(m) * SECONDS_PER_MB >= settings.live_threshold,
                       on_demand=lambda m: on_loop(_on_demand, ls, m),
                       on_busy=lambda m: on_loop(_on_busy, ls, m),
                       on_start=lambda m, measured: on_loop(_on_start, ls, m, measured),
                       on_edit=lambda m: on_loop(_status, ls, m, "save to check", []))
    ls.runner.start()


def _request(ls: DeckServer, uri: str, reason: str) -> None:
    path = _path(uri)
    if path is None:
        ls.protocol.notify("deckcheck/status", {"main": uri, "state": "save to check", "notChecked": []})
        return
    ls.runner.request(path, reason)


def _unchanged_since_checked(ls: DeckServer, path: Path) -> bool:
    """Every model of this file has a result, and the file was not modified after those checks began: reopening it
    needs no new check. Closing and reopening the Yaris main deck restarted its one-minute check (M2b harm gate)."""
    if ls.ws._dirty:  # main decks not known yet: the protocol thread never scans
        return False
    times = [ls.checked_at.get(_key(m)) for m in ls.ws.models_for(path)]
    if not times or None in times:
        return False
    try:
        return path.stat().st_mtime < min(times)
    except OSError:
        return False


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: DeckServer, params: types.DidOpenTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is not None:
        ls.ws.open(path, params.text_document.text)
        ls.edited.discard(_key(path))
        if _unchanged_since_checked(ls, path):
            return
    _request(ls, params.text_document.uri, "open")


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: DeckServer, params: types.DidChangeTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is None:
        return
    ls.edited.add(_key(path))
    ls.ws.change(path, ls.workspace.get_text_document(params.text_document.uri).source)
    _request(ls, params.text_document.uri, "change")


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: DeckServer, params: types.DidSaveTextDocumentParams) -> None:
    ls.ws.mark_dirty()  # includes may have changed: re-detect main decks before the next check
    _request(ls, params.text_document.uri, "save")


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: DeckServer, params: types.DidCloseTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is not None:
        ls.ws.close(path)
        if _key(path) in ls.edited:  # unsaved edits discarded: the disk version applies again
            ls.edited.discard(_key(path))
            ls.runner.request(path, "external")
        else:  # no check, but the worker frees the parses of models that no longer have an open file
            ls.runner.request(path, "close")


def _watched_paths(ws: Workspace, changes) -> list[Path]:
    """Files changed outside the editor. An open file's text is the editor's, and its own save already asked for
    a check: a watcher event for it would only discard that check and run it again."""
    paths = [_path(c.uri) for c in changes]
    return [p for p in paths if p is not None and not ws.synced(p)]


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def watched(ls: DeckServer, params: types.DidChangeWatchedFilesParams) -> None:
    paths = _watched_paths(ls.ws, params.changes)
    if paths:
        ls.ws.mark_dirty()
    for path in paths:
        ls.ws.drop_file(path)
        ls.runner.request(path, "external")


def _reason(params) -> str:
    """The client reports a save of a file it does not sync through deckcheck/check: that is a save (its model's
    files changed), not a repeat click, which a running check would answer as "already checking"."""
    # a custom method's params arrive as pygls' generic object, or a dict in some versions
    reason = params.get("reason") if isinstance(params, dict) else getattr(params, "reason", None)
    return "save" if reason == "save" else "check"


@server.feature("deckcheck/check")
def check_file(ls: DeckServer, params) -> None:
    """The engineer asked ("Check now"), or saved a file the client does not sync: always checks, except a click on
    a model being checked now, which is answered at once (the worker reads requests only between checks)."""
    uri = params["uri"] if isinstance(params, dict) else params.uri
    reason, path = _reason(params), _path(uri)
    if reason == "check" and path is not None:
        mains = ls.ws.models_for(path)  # a lookup in the last scan (spec §3)
        if all(ls.runner.key(m) in ls.checking for m in mains):
            for m in mains:
                _on_busy(ls, m)
            return
    _request(ls, uri, reason)


@server.feature("deckcheck/opened")
def opened_file(ls: DeckServer, params) -> None:
    """A file the client does not sync was opened (its large-tab route): an opening, so a big model waits."""
    _request(ls, params["uri"] if isinstance(params, dict) else params.uri, "open")


@server.feature("deckcheck/active")
def active(ls: DeckServer, params) -> dict | None:
    """The file in front of the engineer: its model goes first in the queue, and the client shows that model's
    status. None while main decks are not known yet."""
    path = _path(params["uri"] if isinstance(params, dict) else params.uri)
    if path is None:
        return None
    # a lookup in the last scan, never a scan (spec §3); while main decks are being re-detected (after a save, for
    # the length of a big check) the last scan's answer beats none, but the queue hint waits for the new one
    main = ls.ws.models_for(path)[0]
    if not ls.ws._dirty:
        ls.runner.active = ls.runner.key(main)
    return {"main": from_fs_path(str(main))}


@server.feature("deckcheck/ping")
def ping(ls: DeckServer, params) -> dict:
    return {"ok": True, "active": ls.runner.active, "caches": len(ls.ws._caches)}


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: DeckServer, params: types.HoverParams) -> types.Hover | None:
    path = _path(params.text_document.uri)
    return features.hover(ls, path, params.position) if path else None


if os.environ.get("DECKCHECK_TEST_HOOKS") == "1":  # tests only: hold the lock the worker holds while freeing parses
    @server.feature("deckcheck/testHoldReading")
    def hold_reading(ls: DeckServer, params) -> dict:
        seconds = params["seconds"] if isinstance(params, dict) else params.seconds
        held = threading.Event()

        def hold():
            with ls.ws.reading:
                held.set()
                time.sleep(seconds)
        threading.Thread(target=hold, daemon=True).start()
        return {"held": held.wait(5)}


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition(ls: DeckServer, params: types.DefinitionParams) -> list[types.Location] | None:
    path = _path(params.text_document.uri)
    return features.definition(ls, path, params.position) if path else None


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def references(ls: DeckServer, params: types.ReferenceParams) -> list[types.Location] | None:
    path = _path(params.text_document.uri)
    return features.references(ls, path, params.position, params.context.include_declaration) if path else None


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(ls: DeckServer, params: types.DocumentSymbolParams) -> list[types.DocumentSymbol]:
    path = _path(params.text_document.uri)
    return features.outline(ls, path) if path else []
