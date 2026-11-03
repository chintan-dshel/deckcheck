import asyncio
import os

from lsprotocol import types

from tests.test_lsp_server import open_doc, published, session, uri
from tests.test_navigate import MAIN, i10, model

HOOKS = {**os.environ, "DECKCHECK_TEST_HOOKS": "1"}


def pos(line, character):
    return types.Position(line - 1, character)


async def hover(client, path, line, character):
    return await client.text_document_hover_async(types.HoverParams(
        types.TextDocumentIdentifier(uri(path)), pos(line, character)))


async def test_hover_on_a_reference_across_includes(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        h = await hover(client, main, 6, 29)
        assert "mid → MAT 1, *MAT_ELASTIC at mat.k:3" in h.contents.value


async def test_hover_before_a_check_and_after_an_edit_says_nothing(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path, liveThresholdSeconds=0) as client:   # a big model: never checked on open
        open_doc(client, main)
        await asyncio.sleep(1)
        assert await hover(client, main, 6, 29) is None
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(version=2, uri=uri(main)),
            [types.TextDocumentContentChangeWholeDocument(MAIN.replace("plate", "plate2"))]))
        assert await hover(client, main, 6, 29) is None              # until the re-check
        await published(client, uri(main))
        assert await hover(client, main, 6, 29) is not None


async def test_hover_after_non_ascii_text(tmp_path):
    # one character in pid's slot padding that is two UTF-16 units: M1 sees mid at column 29, the editor at 30
    main = model(tmp_path)
    text = MAIN.replace(i10(1, 1, 1), "\U0001F600" + i10(1, 1, 1)[1:])
    async with session(tmp_path) as client:
        open_doc(client, main, text)                                  # synced: M1 reads the editor's text
        await published(client, uri(main))
        h = await hover(client, main, 6, 30)
        assert "**mid**" in h.contents.value and h.range.start.character == 30


async def test_request_during_a_drain_returns_nothing(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path, env=HOOKS) as client:
        open_doc(client, main)
        await published(client, uri(main))
        reply = await client.protocol.send_request_async("deckcheck/testHoldReading", {"seconds": 1.0})
        assert (reply["held"] if isinstance(reply, dict) else reply.held) is True
        assert await hover(client, main, 6, 29) is None
