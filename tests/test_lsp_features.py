import asyncio
import os
import time

import pytest
from lsprotocol import types

from tests.test_lsp_server import open_doc, published, session, uri
from deckcheck.navigate import MAX_OUTLINE
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


async def symbols(client, path):
    return await client.text_document_document_symbol_async(types.DocumentSymbolParams(
        types.TextDocumentIdentifier(uri(path))))


async def test_outline_follows_unsaved_text_of_a_small_file(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert (await symbols(client, main))[2].name == "*PART 1 plate"
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(version=2, uri=uri(main)),
            [types.TextDocumentContentChangeWholeDocument(MAIN.replace("plate", "door"))]))
        assert (await symbols(client, main))[2].name == "*PART 1 door"          # before the re-check (D1)


async def test_outline_off_says_why(tmp_path):
    body = "*KEYWORD\n" + ("*DEFINE_CURVE\n" + i10(1) + "\n") * (MAX_OUTLINE + 1) + "*END\n"
    (tmp_path / "main.k").write_text(body)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await published(client, uri(tmp_path / "main.k"))
        got = await symbols(client, tmp_path / "main.k")
        assert len(got) == 1 and got[0].name.startswith("Outline off: 10,002 keywords")


async def test_inlay_hints_for_the_visible_range(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        got = await client.text_document_inlay_hint_async(types.InlayHintParams(
            types.TextDocumentIdentifier(uri(main)), types.Range(pos(16, 0), pos(16, 80))))
        assert [h.label for h in got][:3] == ["eid", "pid", "n1"]


async def code_actions(client, path, line, character):
    return await client.text_document_code_action_async(types.CodeActionParams(
        types.TextDocumentIdentifier(uri(path)), types.Range(pos(line, character), pos(line, character)),
        types.CodeActionContext([])))


async def test_insert_field_ruler_above_a_card(tmp_path):
    main = model(tmp_path)
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        acts = await code_actions(client, main, 6, 3)
        assert [a.title for a in acts] == ["Insert field ruler"]
        edit = acts[0].edit.changes[uri(main)][0]
        assert edit.range.start == pos(6, 0) and edit.new_text.startswith("$#     pid     secid       mid")


async def test_no_ruler_on_a_comma_separated_card(tmp_path):
    main = model(tmp_path, MAIN.replace(i10(1, 1, 1), "1,1,1"))
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        assert not await code_actions(client, main, 6, 0)


async def eventually(f, seconds=10.0):
    end = time.monotonic() + seconds
    while (got := await f()) is None and time.monotonic() < end:
        await asyncio.sleep(0.1)
    return got


async def test_a_file_opened_after_the_check_navigates(tmp_path):
    # review C1: opening an include after the check (F12 from main.k) dropped its parse, and no check followed
    main = model(tmp_path)
    mat = tmp_path / "mat.k"
    async with session(tmp_path) as client:
        open_doc(client, main)
        await published(client, uri(main))
        open_doc(client, mat)
        h = await eventually(lambda: hover(client, mat, 3, 9))
        assert h is not None and "Defines MAT 1" in h.contents.value
        assert spans(await references(client, mat, 3, 9)) == [(uri(main), 6, 29, 30)]
        client.text_document_did_close(types.DidCloseTextDocumentParams(types.TextDocumentIdentifier(uri(mat))))
        d = await eventually(lambda: definition(client, main, 6, 29))
        assert spans(d) == [(uri(mat), 3, 9, 10)]


async def test_a_disk_file_opened_later_keeps_its_columns(tmp_path):
    # part.k checked from disk (a UTF-8 é is two Latin-1 characters to M1), then opened: the editor shows one character
    model(tmp_path, "*KEYWORD\n*INCLUDE\nmat.k\n*INCLUDE\npart.k\n*END\n",
          files={"mat.k": MAT, "part.k": "*KEYWORD\n*PART\nplate\n" + "Ã©" + i10(1, 1, 1)[2:]
                 + "\n*SECTION_SHELL\n" + i10(1, 2) + "\n*END\n"})
    part = tmp_path / "part.k"
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "mat.k")
        await published(client, uri(tmp_path / "mat.k"))
        open_doc(client, part)
        h = await eventually(lambda: hover(client, part, 4, 28))
        assert h is not None and "**mid**" in h.contents.value and h.range.start.character == 28


async def test_a_target_file_edited_since_the_check_is_not_pointed_at(tmp_path):
    # review I1: definition into mat.k after mat.k gained two lines pointed at its old line 3
    main = model(tmp_path)
    mat = tmp_path / "mat.k"
    async with session(tmp_path) as client:
        open_doc(client, main)
        open_doc(client, mat)
        await published(client, uri(main))
        client.text_document_did_change(types.DidChangeTextDocumentParams(
            types.VersionedTextDocumentIdentifier(version=2, uri=uri(mat)),
            [types.TextDocumentContentChangeWholeDocument("$ a\n$ b\n" + MAT)]))
        d = await definition(client, main, 6, 29)
        assert (uri(mat), 3, 9, 10) not in spans(d or [])
        assert "mat.k:3" not in ((await hover(client, main, 6, 29)) or types.Hover("")).contents.value


async def test_a_released_model_keeps_no_navigation_index(tmp_path):
    # review I3: a model released in its own check's clean-up had its index installed after it was forgotten
    main = model(tmp_path)
    async with session(tmp_path) as client:
        client.protocol.notify("deckcheck/check", {"uri": uri(main)})   # no open file: released after the check
        await published(client, uri(main))
        await asyncio.sleep(0.5)
        reply = await client.protocol.send_request_async("deckcheck/ping", {})
        assert (reply["navs"] if isinstance(reply, dict) else reply.navs) == 0


@pytest.mark.parametrize("kind", ["long_line", "binary", "nul"])
async def test_features_on_hostile_files(tmp_path, kind):
    body = {"long_line": b"*KEYWORD\n*NODE\n" + b"1" * 2**20 + b"\n*END\n",
            "binary": bytes(range(256)) * 4096,
            "nul": b"*KEYWORD\n*PART\n\x00\x00\x00\n*END\n"}[kind]
    (tmp_path / "main.k").write_bytes(body)
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await asyncio.sleep(2)
        for line in (1, 2, 3):
            t = time.monotonic()
            await hover(client, tmp_path / "main.k", line, 5)
            await definition(client, tmp_path / "main.k", line, 5)
            await references(client, tmp_path / "main.k", line, 5)
            await symbols(client, tmp_path / "main.k")
            await code_actions(client, tmp_path / "main.k", line, 5)
            await client.text_document_inlay_hint_async(types.InlayHintParams(
                types.TextDocumentIdentifier(uri(tmp_path / "main.k")), types.Range(pos(1, 0), pos(40, 0))))
            assert time.monotonic() - t < 1.0
        reply = await client.protocol.send_request_async("deckcheck/ping", {})
        assert (reply["ok"] if isinstance(reply, dict) else reply.ok) is True
