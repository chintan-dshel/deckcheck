"""Split a deck file into keyword blocks and cards, with positions. Never interprets a keyword's meaning (spec §2)."""
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


def _lines(path: Path) -> list[str]:
    return _split(path.read_bytes().decode("latin-1"))


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
