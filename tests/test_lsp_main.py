import json
import subprocess
import sys

import pytest

from deckcheck.lsp.__main__ import watch


def test_watch_stops_over_budget():
    calls = []
    watch(100, rss=iter([50, 80, 150]).__next__, stop=lambda: calls.append("stop"), sleep=lambda s: None)
    assert calls == ["stop"]


def _frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def test_server_exits_75_over_budget():
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}, "initializationOptions": {"memoryMB": 1}}}
    proc = subprocess.Popen([sys.executable, "-m", "deckcheck.lsp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.write(_frame(init))
    proc.stdin.flush()
    assert proc.wait(timeout=30) == 75
    assert b"memory budget 1 MB exceeded" in proc.stderr.read()


def test_priority_is_below_normal():
    psutil = pytest.importorskip("psutil")
    code = ("from deckcheck.lsp.__main__ import lower_priority; lower_priority(); "
            "import psutil; print(psutil.Process().nice())")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    want = psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 10
    assert int(out) == int(want)
