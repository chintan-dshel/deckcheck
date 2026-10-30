"""Split a deck file into keyword blocks and cards, with positions. Never interprets a keyword's meaning (spec §2)."""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from deckcheck.keywords import Resolved, resolve

STOP_AT_END = True  # torture end_main: LS-DYNA ignores text after *END


class Card(NamedTuple):
    line: int  # 1-based
    text: str  # without the line ending; one character per byte (Latin-1), so a column is a byte offset

    @property
    def free(self) -> bool:
        return "," in self.text


@dataclass
class Block:
    name: str
    line: int
    resolved: Resolved | None
    cards: list[Card] = field(default_factory=list)
    text: str = ""  # the keyword line as read (*KEYWORD LONG=Y needs it; M2 reads it instead of the disk)


@dataclass
class SourceFile:
    path: Path
    blocks: list[Block]
    end_line: int | None


def _split(text: str) -> list[str]:
    # split on '\n' only: str.splitlines() would also break on Latin-1 bytes such as \x85
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


def _open(path: Path):
    """Open for reading without locking the file against deletion or rename (M2 spec §3: an editor saving by
    rename, or a user deleting a file, must never fail because deckcheck is reading it). Windows' default open
    leaves out FILE_SHARE_DELETE; POSIX never locks."""
    if sys.platform != "win32":
        return open(path, "rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    # GENERIC_READ; share read, write and delete; OPEN_EXISTING; FILE_ATTRIBUTE_NORMAL
    handle = k32.CreateFileW(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())  # an OSError subclass, as open() raises
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb")


def _lines(path: Path, chunk: int = 1 << 20) -> list[str]:
    """As _split of the whole file, decoded and split a chunk at a time: one decode or split of a 170 MB file holds
    Python's GIL for about 250 ms, which would stall the language server's protocol thread (M2 spec §3)."""
    out: list[str] = []
    tail = ""
    with _open(path) as f:
        while block := f.read(chunk):
            parts = (tail + block.decode("latin-1")).split("\n")
            tail = parts.pop()
            out.extend(parts)
    out.append(tail)
    if out[-1] == "":
        out.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in out]


def _name(line: str) -> str:
    head = line.split("$", 1)[0][1:].split(None, 1)
    return head[0].rstrip("+-").upper() if head else ""


def read_file(path: Path, text: str | None = None) -> SourceFile:
    """text: the file's content when it must not come from disk (an editor's unsaved buffer, M2)."""
    blocks: list[Block] = []
    for n, line in enumerate(_lines(path) if text is None else _split(text), start=1):
        if line.startswith("$"):
            continue
        if line.startswith("*"):
            name = _name(line)
            if name == "END" and STOP_AT_END:
                return SourceFile(path, blocks, n)
            blocks.append(Block(name, n, resolve(line), text=line))
        elif blocks:
            blocks[-1].cards.append(Card(n, line))
    return SourceFile(path, blocks, None)


def _stream(path: Path):
    with _open(path) as f:
        for raw in f:  # binary iteration splits on b"\n" only, as _split does
            line = raw.decode("latin-1")
            if line.endswith("\n"):
                line = line[:-1]
            yield line[:-1] if line.endswith("\r") else line


def read_includes(path: Path, text: str | None = None) -> SourceFile:
    """Only the *INCLUDE* blocks, to find which files a deck pulls in without parsing it (M2 spec §4.4). Streams
    from disk, so a large mesh file is never held in memory."""
    blocks: list[Block] = []
    keep = False
    for n, line in enumerate(_stream(path) if text is None else _split(text), start=1):
        if line.startswith("$"):
            continue
        if line.startswith("*"):
            name = _name(line)
            if name == "END" and STOP_AT_END:
                return SourceFile(path, blocks, n)
            keep = name.startswith("INCLUDE")
            if keep:
                blocks.append(Block(name, n, resolve(line), text=line))
        elif keep:
            blocks[-1].cards.append(Card(n, line))
    return SourceFile(path, blocks, None)
