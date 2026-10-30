import asyncio
import os
import random
import sys
import time
from pathlib import Path

import pytest
from lsprotocol import types

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST
from deckcheck.includes import resolve_tree
from tests.test_lsp_server import open_doc, published, session, uri

STRESS = pytest.mark.skipif(os.environ.get("DECKCHECK_STRESS") != "1", reason="set DECKCHECK_STRESS=1")


def _entry(name):
    return next(e for e in load_manifest(MANIFEST) if e.name.startswith(name))


async def _ping_ms(client) -> float:
    t = time.monotonic()
    await client.protocol.send_request_async("deckcheck/ping", {})
    return (time.monotonic() - t) * 1000


def _state(client) -> str:
    s = client.statuses[-1]
    return s["state"] if isinstance(s, dict) else s.state


@pytest.mark.corpus
@pytest.mark.parametrize("name, include, up", [("vivaplus", "vivaplus-joints.k", 1),  # in model/common
                                               ("ccsa-yaris", "set-yaris-detailed-v2j.key", 0)])
async def test_real_include_opened_without_false_errors(name, include, up):
    main = Path(os.path.abspath(fetch(_entry(name))))
    target = next(f.path for f in resolve_tree(main).files if f.path.name == include)
    async with session(main.parents[up]) as client:
        t = time.monotonic()
        open_doc(client, target)
        await published(client, uri(main), timeout=600)
        print(f"{name}: first diagnostics after {time.monotonic() - t:.1f} s")
        assert not [d for u in client.diagnostics for d in client.diagnostics[u] if d.code == "DC001"]
        assert await _ping_ms(client) < 100


@pytest.mark.corpus
async def test_ping_stays_fast_during_a_yaris_check():
    main = Path(os.path.abspath(fetch(_entry("ccsa-yaris"))))
    async with session(main.parent) as client:
        client.protocol.notify("deckcheck/check", {"uri": uri(main)})
        await asyncio.sleep(5)  # the check is running
        pings = [await _ping_ms(client) for _ in range(20)]
        print(f"yaris pings: worst {max(pings):.1f} ms")
        assert max(pings) < 100, pings


async def _ends_well(client, target: Path, timeout=600):
    """The harm rule: either deckcheck answers, or the server paused itself (exit 75); never a hang or a crash."""
    try:
        await published(client, uri(target), timeout=timeout)
        assert await _ping_ms(client) < 100
        return "checked"
    except Exception as e:
        print(f"no diagnostics ({e!r}); expecting the server to have paused")
        code = await asyncio.wait_for(client._server.wait(), 10)
        assert code == 75, code
        return "paused"


@STRESS
@pytest.mark.corpus
async def test_four_occupants_check_or_pause():
    # VIVA+ resolves its includes from the main deck's folder (LS-DYNA's rule), so the four-occupant deck sits
    # beside VIVA+'s own main deck in the (git-ignored) corpus cache, and is removed afterwards.
    viva = Path(os.path.abspath(fetch(_entry("vivaplus"))))
    cards = []
    for i in range(4):
        off = f"{(i + 1) * 10_000_000:>10}"
        cards += ["*INCLUDE_TRANSFORM", viva.name, off * 7, off * 3, "         0"]
    main = viva.parent / "deckcheck-stress-four.k"
    main.write_text("*KEYWORD\n" + "\n".join(cards) + "\n*END\n", encoding="latin-1")
    try:
        assert len(resolve_tree(main).files) > 4 * 17 and not resolve_tree(main).problems  # every include found
        async with session(viva.parent, mainDecks=[main.name]) as client:
            t = time.monotonic()
            open_doc(client, main)
            outcome = await _ends_well(client, main)
            print(f"four occupants: {outcome} after {time.monotonic() - t:.1f} s")
            if outcome == "checked":
                assert not [d for u in client.diagnostics for d in client.diagnostics[u] if d.code == "DC004"]
    finally:
        main.unlink()


@STRESS
async def test_huge_unsynced_mesh_checks_or_pauses(tmp_path):
    deck = tmp_path / "mesh.k"
    with open(deck, "w", encoding="latin-1") as f:
        f.write("*KEYWORD\n*NODE\n")
        for n in range(1, 5_500_001):  # about 300 MB
            f.write(f"{n:>8}{n * 0.001:>16.6f}{0.0:>16.6f}{0.0:>16.6f}\n")
        f.write("*END\n")
    async with session(tmp_path) as client:
        t = time.monotonic()
        client.protocol.notify("deckcheck/check", {"uri": uri(deck)})
        print(f"huge mesh ({deck.stat().st_size >> 20} MB): {await _ends_well(client, deck)} "
              f"after {time.monotonic() - t:.1f} s")


@STRESS
@pytest.mark.parametrize("kind", ["long_line", "binary", "nul"])
async def test_hostile_files_never_break_the_server(tmp_path, kind):
    deck = tmp_path / "x.k"
    random.seed(7)
    data = {"long_line": b"*KEYWORD\n" + b"1" * 1_000_000 + b"\n*END\n",
            "binary": bytes(random.randrange(256) for _ in range(1_000_000)),
            "nul": b"*KEYWORD\n*PART\np\x00\n\x00\x00\x00         1\n*END\n"}[kind]
    deck.write_bytes(data)
    async with session(tmp_path) as client:
        open_doc(client, deck, text=data.decode("utf-8", errors="replace"))
        assert await _ends_well(client, deck, timeout=60) == "checked"


@STRESS
async def test_include_deleted_and_locked_during_a_check(tmp_path):
    big = tmp_path / "mesh.k"
    with open(big, "w", encoding="latin-1") as f:
        f.write("*KEYWORD\n*NODE\n" + "".join(f"{n:>8}{0.0:>16}{0.0:>16}{0.0:>16}\n" for n in range(1, 300_001))
                + "*END\n")
    (tmp_path / "main.k").write_text("*KEYWORD\n*INCLUDE\nmesh.k\n*END\n", encoding="latin-1")
    async with session(tmp_path) as client:
        open_doc(client, tmp_path / "main.k")
        await asyncio.sleep(0.2)
        big.unlink()
        await published(client, uri(tmp_path / "main.k"), timeout=120)
        assert await _ping_ms(client) < 100
        if sys.platform == "win32":
            import msvcrt
            big.write_text("*KEYWORD\n*END\n", encoding="latin-1")
            with open(big, "r+b") as f:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                client.protocol.notify("deckcheck/check", {"uri": uri(tmp_path / "main.k")})
                await published(client, uri(tmp_path / "main.k"), timeout=60)
                await asyncio.sleep(0.2)
                assert _state(client) in ("ok", "check failed")
                assert await _ping_ms(client) < 100
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@STRESS
async def test_fifty_open_includes_and_a_minute_of_typing(tmp_path):
    names = [f"inc{i:02}.k" for i in range(50)]
    (tmp_path / "main.k").write_text("*KEYWORD\n" + "".join(f"*INCLUDE\n{n}\n" for n in names) + "*END\n",
                                     encoding="latin-1")
    for i, n in enumerate(names):
        (tmp_path / n).write_text(f"*KEYWORD\n*PART\np{i}\n{i + 1:>10}         1         1\n*END\n",
                                  encoding="latin-1")
    async with session(tmp_path) as client:
        for n in names:
            open_doc(client, tmp_path / n)
        target, text, worst = tmp_path / names[0], (tmp_path / names[0]).read_text(encoding="latin-1"), 0.0
        end = time.monotonic() + 60
        version = 1
        while time.monotonic() < end:
            version += 1
            text += "$"
            client.text_document_did_change(types.DidChangeTextDocumentParams(
                types.VersionedTextDocumentIdentifier(uri=uri(target), version=version),
                [types.TextDocumentContentChangeWholeDocument(text=text)]))
            await asyncio.sleep(0.05)
            if version % 10 == 0:
                worst = max(worst, await _ping_ms(client))
        print(f"fifty includes, {version} edits: worst ping {worst:.1f} ms")
        assert worst < 100, worst
        await published(client, uri(tmp_path / "main.k"), timeout=30)
