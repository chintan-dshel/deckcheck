import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from lsprotocol import types
from pygls.uris import from_fs_path
from pytest_lsp import client_capabilities, make_test_lsp_client

from deckcheck.lsp.convert import utf16_column
from deckcheck.rules import check

TORTURE = Path(__file__).parent / "torture"
CASES = sorted(p.parent.name for p in TORTURE.glob("*/expected.toml"))


@asynccontextmanager
async def session(folder: Path, **options):
    client = make_test_lsp_client()
    client.statuses = []
    client.feature("deckcheck/status")(lambda ls, params: ls.statuses.append(params))
    await client.start_io(sys.executable, "-m", "deckcheck.lsp")
    await client.initialize_session(types.InitializeParams(
        capabilities=client_capabilities("visual-studio-code"),
        workspace_folders=[types.WorkspaceFolder(uri=from_fs_path(os.path.abspath(folder)), name="ws")],
        initialization_options=options))
    try:
        yield client
    finally:
        await client.shutdown_session()


def uri(path: Path) -> str:
    return from_fs_path(os.path.abspath(path))


def editor_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")  # what VS Code shows by default


def open_doc(client, path: Path, text: str | None = None, version: int = 1) -> None:
    client.text_document_did_open(types.DidOpenTextDocumentParams(types.TextDocumentItem(
        uri=uri(path), language_id="keyword-deck", version=version,
        text=editor_text(path) if text is None else text)))


async def published(client, target: str, timeout: float = 30.0):
    client.diagnostics.pop(target, None)
    deadline = time.monotonic() + timeout
    while target not in client.diagnostics:
        await asyncio.wait_for(client.wait_for_notification("textDocument/publishDiagnostics"),
                               max(0.01, deadline - time.monotonic()))
    return client.diagnostics[target]


async def last_status(client, before: int, timeout: float = 10.0) -> str:
    """The state of the first deckcheck/status after `before` statuses had arrived (it follows the diagnostics)."""
    deadline = time.monotonic() + timeout
    while len(client.statuses) <= before:
        await asyncio.wait_for(client.wait_for_notification("deckcheck/status"),
                               max(0.01, deadline - time.monotonic()))
    s = client.statuses[-1]
    return s["state"] if isinstance(s, dict) else s.state


def _expected(main: Path) -> set[tuple]:
    rep = check(main)
    out = set()
    for d in rep.diagnostics:
        raw = d.path.read_bytes().decode("latin-1").split("\n")[d.line - 1].rstrip("\r")
        out.add((uri(d.path), d.line - 1, utf16_column(raw, d.start, True), utf16_column(raw, d.end, True),
                 d.code, d.message))
    return out


def _got(client, uris) -> set[tuple]:
    return {(u, d.range.start.line, d.range.start.character, d.range.end.character, d.code, d.message)
            for u in uris for d in client.diagnostics.get(u, [])}


async def test_parity_with_the_cli_on_every_torture_deck():
    async with session(TORTURE) as client:
        for case in CASES:
            main = TORTURE / case / "main.k"
            open_doc(client, main)
            await published(client, uri(main))
            files = {uri(f.path) for f in check(main).tree.files}
            assert _got(client, files) == _expected(main), case


async def test_unsaved_edit_is_rechecked_within_one_second(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path) as client:
        open_doc(client, deck)
        assert not [d for d in await published(client, uri(deck)) if d.code == "DC001"]
        text = editor_text(deck).replace("plate\n         1         1         1", "plate\n         1         1        99")
        t = time.monotonic()
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri=uri(deck), version=2),
            [types.TextDocumentContentChangeWholeDocument(text=text)]))
        diags = await published(client, uri(deck), timeout=5)
        assert [d for d in diags if d.code == "DC001"] and time.monotonic() - t < 1.0


async def test_big_model_waits_for_save(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path, liveThresholdSeconds=0) as client:
        open_doc(client, deck)                     # big: no check on open, the engineer is asked instead
        assert await last_status(client, 0) == "click to check"
        with pytest.raises(asyncio.TimeoutError):
            await published(client, uri(deck), timeout=1.5)
        client.protocol.notify("deckcheck/check", {"uri": uri(deck)})   # "Check now"
        await published(client, uri(deck))
        assert (await summarized(client))["state"] == "checks on save"
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri=uri(deck), version=2),
            [types.TextDocumentContentChangeWholeDocument(text=editor_text(deck) + "$ edit\n")]))
        with pytest.raises(asyncio.TimeoutError):
            await published(client, uri(deck), timeout=1.5)
        client.text_document_did_save(types.DidSaveTextDocumentParams(types.TextDocumentIdentifier(uri(deck))))
        await published(client, uri(deck), timeout=5)


MAIN = "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n"
PART = "*KEYWORD\n*PART\np\n         1         1         1\n*SECTION_SHELL\n         1\n*END\n"
MAT = "*KEYWORD\n*MAT_ELASTIC\n         1   7.85E-9  210000.0       0.3\n*END\n"


def _model(tmp):
    for name, text in {"main.k": MAIN, "part.k": PART, "mat.k": MAT}.items():
        (tmp / name).write_text(text, encoding="latin-1")


async def test_include_opened_alone_has_no_false_dc001(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "part.k")
        await published(client, uri(tmp_path / "main.k"))
        assert not [d for u in client.diagnostics for d in client.diagnostics[u] if d.code == "DC001"]


async def test_unsaved_include_is_checked(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k", text=MAT.replace("         1", "         7", 1))
        await published(client, uri(tmp_path / "main.k"))
        assert [d for d in client.diagnostics[uri(tmp_path / "part.k")] if d.code == "DC001"]


async def test_check_notification_reads_an_unsynced_file_from_disk(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        client.protocol.notify("deckcheck/check", {"uri": uri(tmp_path / "part.k")})
        await published(client, uri(tmp_path / "main.k"))


async def test_failed_check_clears_and_reports(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path) as client:
        open_doc(client, deck)
        await published(client, uri(deck))
        before = len(client.statuses)
        deck.unlink()  # the main deck vanishes: the next whole check fails
        client.text_document_did_save(types.DidSaveTextDocumentParams(types.TextDocumentIdentifier(uri(deck))))
        assert list(await published(client, uri(deck))) == []
        assert await last_status(client, before) == "check failed"


async def test_untitled_document_is_not_checked(tmp_path):
    async with session(tmp_path) as client:
        client.text_document_did_open(types.DidOpenTextDocumentParams(types.TextDocumentItem(
            uri="untitled:Untitled-1", language_id="keyword-deck", version=1, text="*KEYWORD\n")))
        assert await last_status(client, 0) == "save to check"


async def test_ping_answers(tmp_path):
    async with session(tmp_path) as client:
        reply = await client.protocol.send_request_async("deckcheck/ping", {})
        assert (reply["ok"] if isinstance(reply, dict) else reply.ok) is True


async def test_former_main_now_included_loses_its_findings(tmp_path):
    (tmp_path / "part.k").write_text(PART, encoding="latin-1")
    (tmp_path / "mat.k").write_text(MAT, encoding="latin-1")
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "part.k")    # nothing includes it yet: checked alone, MAT 1 missing
        assert [d for d in await published(client, uri(tmp_path / "part.k")) if d.code == "DC001"]
        (tmp_path / "main.k").write_text(MAIN, encoding="latin-1")
        client.text_document_did_save(types.DidSaveTextDocumentParams(types.TextDocumentIdentifier(uri(tmp_path / "part.k"))))
        await published(client, uri(tmp_path / "main.k"))
        assert not [d for d in client.diagnostics[uri(tmp_path / "part.k")] if d.code == "DC001"]


def test_watcher_events_for_synced_files_are_ignored(tmp_path):
    from deckcheck.lsp.server import _watched_paths
    from deckcheck.lsp.workspace import Settings, Workspace
    ws = Workspace([tmp_path], Settings())
    ws.open(tmp_path / "open.k", "*KEYWORD\n")
    changes = [types.FileEvent(uri(tmp_path / n), types.FileChangeType.Changed) for n in ("open.k", "closed.k")]
    assert [p.name for p in _watched_paths(ws, changes)] == ["closed.k"]


async def test_active_notification_sets_the_front_of_the_queue(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "part.k")
        await published(client, uri(tmp_path / "main.k"))  # the first check ran the include scan
        client.protocol.notify("deckcheck/active", {"uri": uri(tmp_path / "part.k")})
        reply = await client.protocol.send_request_async("deckcheck/ping", {})
        active = reply["active"] if isinstance(reply, dict) else reply.active
        assert active and active.endswith("main.k")


def _close(client, path):
    client.text_document_did_close(types.DidCloseTextDocumentParams(types.TextDocumentIdentifier(uri(path))))


async def test_reopening_an_unchanged_file_does_not_recheck(tmp_path):
    """Closing and reopening the Yaris main deck restarted its one-minute check each time (M2b harm gate)."""
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await published(client, uri(tmp_path / "main.k"))
        _close(client, tmp_path / "main.k")
        open_doc(client, tmp_path / "main.k", version=2)
        with pytest.raises(asyncio.TimeoutError):
            await published(client, uri(tmp_path / "main.k"), timeout=1.5)


async def test_closing_an_edited_file_rechecks_from_disk(tmp_path):
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k")
        await published(client, uri(tmp_path / "main.k"))
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri=uri(tmp_path / "mat.k"), version=2),
            [types.TextDocumentContentChangeWholeDocument(text=MAT.replace("         1", "         7", 1))]))
        assert [d for d in await published(client, uri(tmp_path / "part.k")) if d.code == "DC001"]
        _close(client, tmp_path / "mat.k")            # unsaved edit discarded: the disk version applies again
        assert not [d for d in await published(client, uri(tmp_path / "part.k")) if d.code == "DC001"]


async def test_closing_the_last_file_releases_the_model(tmp_path):
    """An unchanged close starts no check, but the model's parsed files (about 1 GB for the Yaris) must not stay
    resident while nothing of it is open (M2b harm gate)."""
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await published(client, uri(tmp_path / "main.k"))
        _close(client, tmp_path / "main.k")
        end = time.monotonic() + 5
        while True:
            reply = await client.protocol.send_request_async("deckcheck/ping", {})
            caches = reply["caches"] if isinstance(reply, dict) else reply.caches
            if caches == 0 or time.monotonic() > end:
                break
            await asyncio.sleep(0.1)
        assert caches == 0


async def test_opened_notification_is_an_open_not_a_demand(tmp_path):
    """The client's large-tab route reports an opening, which a big model answers with "click to check"."""
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path, liveThresholdSeconds=0) as client:
        client.protocol.notify("deckcheck/opened", {"uri": uri(deck)})
        assert await last_status(client, 0) == "click to check"


def _state(s):
    """A custom notification's params: a dict, or pygls' generic named tuple in some versions."""
    return s if isinstance(s, dict) else s._asdict()


async def summarized(client, timeout: float = 30.0) -> dict:
    """The first status that carries a check's summary (a "checking" status may come before it)."""
    deadline = time.monotonic() + timeout
    while not [s for s in client.statuses if _state(s).get("summary")]:
        await asyncio.wait_for(client.wait_for_notification("deckcheck/status"), max(0.01, deadline - time.monotonic()))
    return [_state(s) for s in client.statuses if _state(s).get("summary")][0]


async def test_an_explicit_big_check_shows_progress_and_a_summary(tmp_path):
    """Trial finding 6: a click ran a silent 70 s check that ended by changing one word. The client now hears that a
    check began (with an estimate) and, at the end, what was covered and what was found."""
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "seeded_mistakes" / "main.k").read_bytes())
    async with session(tmp_path, liveThresholdSeconds=0) as client:
        open_doc(client, deck)
        await last_status(client, 0)
        client.protocol.notify("deckcheck/check", {"uri": uri(deck)})
        await published(client, uri(deck))
        final = await summarized(client)
        checking = [_state(s) for s in client.statuses if _state(s)["state"] == "checking"]
        assert checking and checking[0]["estimate"] > 0
        summary = _state(final["summary"])
        assert summary["explicit"] is True and summary["files"] == 1 and summary["errors"] == 3
        assert summary["warnings"] == 0 and summary["seconds"] >= 0 and summary["mb"] > 0


async def test_a_live_check_sends_no_progress_and_no_explicit_summary(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path) as client:
        open_doc(client, deck)
        await published(client, uri(deck))
        final = await summarized(client)
        assert not [s for s in client.statuses if _state(s)["state"] == "checking"]
        assert _state(final["summary"])["explicit"] is False


async def test_an_edit_to_a_checked_big_model_says_save_to_check(tmp_path):
    deck = tmp_path / "main.k"
    deck.write_bytes((TORTURE / "m1d_base" / "main.k").read_bytes())
    async with session(tmp_path, liveThresholdSeconds=0) as client:
        open_doc(client, deck)
        await last_status(client, 0)
        client.protocol.notify("deckcheck/check", {"uri": uri(deck)})
        await published(client, uri(deck))
        await summarized(client)
        n = len(client.statuses)
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(uri=uri(deck), version=2),
            [types.TextDocumentContentChangeWholeDocument(text=editor_text(deck) + "$ edit\n")]))
        assert await last_status(client, n) == "save to check"


def test_a_save_routed_through_check_counts_as_a_save():
    """Review Critical 1: the client reports saving a file it doesn't sync through deckcheck/check; as a plain check
    it was answered "already checking" during that model's check, and the save was lost."""
    from deckcheck.lsp.server import _reason
    assert _reason({"uri": "file:///x.k", "reason": "save"}) == "save"
    assert _reason({"uri": "file:///x.k"}) == "check"


def test_a_click_always_reports_and_a_save_only_when_the_check_took_long():
    """Review Important 5: a popup per save of a 6 s model is spam; a 70 s one ends while the engineer is elsewhere."""
    from deckcheck.lsp.server import _explicit
    assert _explicit("check", seconds=1.0, live=True) is True       # a click on a mid-size model (review Minor 12)
    assert _explicit("save", seconds=70.0, live=False) is True
    assert _explicit("save", seconds=6.0, live=False) is False
    assert _explicit("save", seconds=0.1, live=True) is False
    assert _explicit("open", seconds=70.0, live=False) is False


async def test_active_answers_with_the_files_model(tmp_path):
    """The status bar shows the model of the file in front of the engineer: the client asks which one that is."""
    _model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "part.k")
        await published(client, uri(tmp_path / "part.k"))
        reply = await client.protocol.send_request_async("deckcheck/active", {"uri": uri(tmp_path / "part.k")})
        main = reply["main"] if isinstance(reply, dict) else reply.main
        assert main == uri(tmp_path / "main.k")
