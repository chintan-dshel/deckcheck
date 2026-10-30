"""Protocol handlers (M2 spec §4.2). Each handler records what changed and asks the runner; none waits for a check
(spec §3). Results are published from the runner's thread through the event loop."""
import asyncio
import gc
from dataclasses import dataclass
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import from_fs_path, to_fs_path

from deckcheck import __version__
from deckcheck.includes import _key, _norm
from deckcheck.lsp.__main__ import start_watchdog
from deckcheck.lsp.convert import merge, to_lsp
from deckcheck.lsp.runner import Runner
from deckcheck.lsp.workspace import Settings, Workspace, drain_index
from deckcheck.rules import check


class DeckServer(LanguageServer):
    ws: Workspace
    runner: Runner
    loop: asyncio.AbstractEventLoop
    results: dict[str, dict[str, list[types.Diagnostic]]]
    names: dict[str, str]


server = DeckServer("deckcheck", __version__)


def _path(uri: str) -> Path | None:
    p = to_fs_path(uri)
    return _norm(Path(p)) if p else None


@dataclass
class Result:
    """What the protocol thread needs from a check; built in the worker so the report is freed there."""
    diagnostics: dict[str, list[types.Diagnostic]]
    not_checked: list[dict]


def _status(ls: DeckServer, main: Path, state: str, items: list[dict]) -> None:
    ls.protocol.notify("deckcheck/status", {"main": from_fs_path(str(main)), "state": state, "notChecked": items})


def _publish(ls: DeckServer, main: Path, result: Result | None, error) -> None:
    k = _key(main)
    previous = set(ls.results.get(k, {}))
    if error is not None or result is None:
        ls.results[k] = {u: [] for u in previous}
        state, items = "check failed", []
        ls.window_log_message(types.LogMessageParams(types.MessageType.Error, f"deckcheck: {main}: {error!r}"))
    else:
        ls.results[k] = result.diagnostics
        for u in previous - set(ls.results[k]):
            ls.results[k][u] = []
        state, items = ("ok" if ls.runner.live(main) else "checks on save"), result.not_checked
    ls.names[k] = main.name
    merged = merge(ls.results, ls.names)
    main_uri = from_fs_path(str(main))
    for u in sorted(ls.results[k], key=lambda u: u == main_uri):  # included files first, the main deck last
        ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=u, diagnostics=merged.get(u, [])))
    _status(ls, main, state, items)


def _check(ls: DeckServer, main: Path) -> Result:
    """Worker thread. Everything that frees or builds big structures happens here, never on the protocol thread:
    a full garbage collection over a big model's millions of objects holds the GIL for ~200 ms (measured on the
    Yaris), so collection pauses during a check and the survivors are frozen out of later scans (still freed by
    reference counting); M1's structures are acyclic. The report's index is emptied a chunk at a time."""
    gc.disable()
    try:
        report = check(main, source=ls.ws.source, cache=ls.ws.cache_for(main))
        report.diagnostics[:] = [d for d in report.diagnostics if d.code not in ls.ws.settings.ignore]
        result = Result(to_lsp(report, ls.ws.synced),
                        [{"what": n.what, "reasons": list(n.reasons), "count": n.count} for n in report.not_checked])
        drain_index(report.index)
        return result
    finally:
        ls.ws.release_closed()
        gc.freeze()
        gc.enable()


def _prepare(ls: DeckServer) -> None:
    ls.ws.apply_drops()
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
    ls.runner = Runner(models=ls.ws.models_for, check=lambda m: _check(ls, m),
                       publish=lambda m, r, e: ls.loop.call_soon_threadsafe(_publish, ls, m, r, e),
                       threshold=settings.live_threshold, prepare=lambda: _prepare(ls))
    ls.runner.start()


def _request(ls: DeckServer, uri: str, reason: str) -> None:
    path = _path(uri)
    if path is None:
        ls.protocol.notify("deckcheck/status", {"main": uri, "state": "save to check", "notChecked": []})
        return
    ls.runner.request(path, reason)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: DeckServer, params: types.DidOpenTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is not None:
        ls.ws.open(path, params.text_document.text)
    _request(ls, params.text_document.uri, "open")


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: DeckServer, params: types.DidChangeTextDocumentParams) -> None:
    path = _path(params.text_document.uri)
    if path is None:
        return
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
        ls.runner.request(path, "external")  # the disk version applies again


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def watched(ls: DeckServer, params: types.DidChangeWatchedFilesParams) -> None:
    ls.ws.mark_dirty()
    for change in params.changes:
        path = _path(change.uri)
        if path is not None:
            ls.ws.drop_file(path)
            ls.runner.request(path, "external")


@server.feature("deckcheck/check")
def check_file(ls: DeckServer, params) -> None:
    # a custom method's params arrive as pygls' generic object, or a dict in some versions
    _request(ls, params["uri"] if isinstance(params, dict) else params.uri, "save")


@server.feature("deckcheck/ping")
def ping(ls: DeckServer, params) -> dict:
    return {"ok": True}
