import asyncio
import os

from lsprotocol import types

from tests.test_lsp_server import open_doc, published, session, uri
from tests.test_navigate import MAIN, MAT, i10, model

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


async def definition(client, path, line, character):
    return await client.text_document_definition_async(types.DefinitionParams(
        types.TextDocumentIdentifier(uri(path)), pos(line, character)))


async def references(client, path, line, character, decl=False):
    return await client.text_document_references_async(types.ReferenceParams(
        context=types.ReferenceContext(include_declaration=decl),
        text_document=types.TextDocumentIdentifier(uri(path)), position=pos(line, character)))


def spans(locs):
    return sorted((l.uri, l.range.start.line + 1, l.range.start.character, l.range.end.character) for l in locs)


async def test_definition_across_includes_and_on_itself(tmp_path):
    main = model(tmp_path)
    mat = tmp_path / "mat.k"
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert spans(await definition(client, main, 6, 29)) == [(uri(mat), 3, 9, 10)]
        assert spans(await definition(client, main, 16, 39)) == [(uri(main), 13, 7, 8)]   # n3 -> NODE 3
        assert spans(await definition(client, main, 6, 9)) == [(uri(main), 6, 9, 10)]     # PART 1 itself


async def test_references_with_and_without_the_declaration(tmp_path):
    main = model(tmp_path)
    mat = tmp_path / "mat.k"
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert spans(await references(client, mat, 3, 9)) == [(uri(main), 6, 29, 30)]
        assert spans(await references(client, main, 6, 29, decl=True)) == [(uri(main), 6, 29, 30), (uri(mat), 3, 9, 10)]


async def test_definition_range_in_a_latin1_file(tmp_path):
    # part.k is never opened, so M1 reads it from disk: a UTF-8 é (two bytes) in pid's padding puts mid at M1
    # column 29 and at editor column 28
    main = model(tmp_path, "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n",
                 files={"mat.k": MAT, "part.k": "*KEYWORD\n*PART\nplate\n" + "Ã©" + i10(1, 1, 1)[2:]
                        + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n*END\n"})
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k")
        await published(client, uri(tmp_path / "mat.k"))
        assert spans(await references(client, tmp_path / "mat.k", 3, 9)) == [(uri(tmp_path / "part.k"), 4, 28, 29)]


async def test_references_from_a_file_in_two_models(tmp_path):
    model(tmp_path)
    (tmp_path / "other.k").write_bytes(b"*KEYWORD\n*INCLUDE\nmat.k\n*PART\nq\n" + i10(2, 1, 1).encode() + b"\n*END\n")
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k")
        await published(client, uri(tmp_path / "mat.k"))
        await asyncio.sleep(2)                                     # both models checked
        got = spans(await references(client, tmp_path / "mat.k", 3, 9))
        assert got == sorted({(uri(tmp_path / "main.k"), 6, 29, 30), (uri(tmp_path / "other.k"), 6, 29, 30)})
