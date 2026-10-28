"""Follow a deck's includes in LS-DYNA's reading order. Every rule here was decided by LS-DYNA on the torture
cases named beside it (docs/m1b-reader-includes.md), not taken from memory."""
import os
from dataclasses import dataclass
from pathlib import Path

from deckcheck.fields import card_values
from deckcheck.keywords import load
from deckcheck.reader import Block, Card, SourceFile, read_file

SEARCH_INCLUDING_DIR = False  # inc_nested_sibling: Error 10087, b.k beside its includer not found
SEARCH_MAIN_DIR = True        # inc_nested_main: accepted
INCLUDING_DIR_FIRST = False   # inc_nested_both: main folder's b.k read (moot: including dir not searched)
PATH_BEFORE_DIRS = False      # inc_path_precedence: main folder's mat.k read
PATH_RELATIVE_TO_FILE = False # inc_path_relative: opened .\lib\mat.k, relative to the main deck
PATH_APPLIES_EARLIER = False  # inc_path_late: Error 10087 for the earlier include
MULTI_FILENAME = True         # inc_multi: accepted
CONTINUATION = True           # inc_continuation: accepted

FOLLOWED = ("INCLUDE", "INCLUDE_TRANSFORM")
PATHS = ("INCLUDE_PATH", "INCLUDE_PATH_RELATIVE")


@dataclass(frozen=True)
class Problem:
    kind: str
    file: Path
    line: int
    columns: tuple[int, int]
    name: str


@dataclass
class FileNode:
    path: Path
    source: SourceFile
    parent: int | None
    line: int | None
    offsets: dict[str, int]


@dataclass
class Tree:
    files: list[FileNode]
    problems: list[Problem]


def _norm(path) -> Path:
    # abspath + normpath, never Path.resolve(): resolve() can add a \\?\ prefix on Windows
    return Path(os.path.normpath(os.path.abspath(path)))


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


def _span(text: str) -> tuple[int, int]:
    return len(text) - len(text.lstrip()), len(text.rstrip())


def _filenames(cards: list[Card]) -> list[tuple[Card, str, int]]:
    """(first card, filename, index of the next card) for each filename; ' +' continues a name on the next card."""
    out, parts, first = [], [], None
    for i, card in enumerate(cards):
        text = card.text.rstrip()
        if not text and first is None:
            continue
        first = first or card
        if CONTINUATION and text.endswith(" +"):
            parts.append(text[:-2].strip())
            continue
        parts.append(text.strip())
        out.append((first, "".join(parts), i + 1))
        parts, first = [], None
    return out


def _locate(name: str, including_dir: Path, main_dir: Path, paths: list[Path]) -> Path | None:
    rel = Path(name.replace("\\", "/"))
    if rel.is_absolute():
        dirs = [Path()]
    else:
        own = [including_dir] if SEARCH_INCLUDING_DIR else []
        top = [main_dir] if SEARCH_MAIN_DIR else []
        dirs = own + top if INCLUDING_DIR_FIRST else top + own
        dirs = paths + dirs if PATH_BEFORE_DIRS else dirs + paths
    for d in dirs:
        candidate = _norm(d / rel)
        if candidate.is_file():
            return candidate
    return None


def _offsets(tree: Tree, node: FileNode, block: Block, start: int) -> dict[str, int]:
    layout = load()["keywords"]["INCLUDE_TRANSFORM"]["cards"][1:3]  # the idnoff... and idroff cards
    out: dict[str, int] = {}
    for spec, card in zip(layout, block.cards[start:start + 2] + [Card(0, "")] * 2):
        fields = [f for f in spec["fields"] if f["name"].startswith("id") and f["name"].endswith("off")]
        for name, value in card_values(card, fields).items():
            try:
                out[name] = int(value) if value else 0
            except ValueError:
                tree.problems.append(Problem("unread", node.path, card.line, _span(card.text), value))
                out[name] = 0
    return out


def _walk(tree: Tree, index: int, chain: list[str], main_dir: Path, paths: list[Path],
          cache: dict[str, SourceFile]) -> None:
    node = tree.files[index]
    for block in node.source.blocks:
        if block.name in PATHS:
            relative = block.name == "INCLUDE_PATH_RELATIVE" and PATH_RELATIVE_TO_FILE
            base = node.path.parent if relative else main_dir
            for card in block.cards:
                if card.text.strip():
                    d = _norm(base / card.text.strip().replace("\\", "/"))
                    if d not in paths:
                        paths.append(d)
        elif block.name in FOLLOWED:
            names = _filenames(block.cards)
            if block.name == "INCLUDE_TRANSFORM" or not MULTI_FILENAME:
                names = names[:1]
            for card, name, after in names:
                found = _locate(name, node.path.parent, main_dir, paths)
                if found is None:
                    tree.problems.append(Problem("missing", node.path, card.line, _span(card.text), name))
                    continue
                if _key(found) in chain:
                    tree.problems.append(Problem("cycle", node.path, card.line, _span(card.text), name))
                    continue
                offsets = _offsets(tree, node, block, after) if block.name == "INCLUDE_TRANSFORM" else {}
                if _key(found) not in cache:
                    cache[_key(found)] = read_file(found)
                tree.files.append(FileNode(found, cache[_key(found)], index, card.line, offsets))
                _walk(tree, len(tree.files) - 1, chain + [_key(found)], main_dir, paths, cache)
        elif block.name.startswith("INCLUDE"):
            tree.problems.append(Problem("unfollowed", node.path, block.line, (1, 1 + len(block.name)), block.name))


def _build(main: Path, paths: list[Path], cache: dict[str, SourceFile]) -> Tree:
    if _key(main) not in cache:
        cache[_key(main)] = read_file(main)
    tree = Tree([FileNode(main, cache[_key(main)], None, None, {})], [])
    _walk(tree, 0, [_key(main)], main.parent, paths, cache)
    return tree


def resolve_tree(main: Path) -> Tree:
    main = _norm(main)
    if not main.is_file():
        raise FileNotFoundError(main)
    cache: dict[str, SourceFile] = {}
    paths: list[Path] = []
    tree = _build(main, paths, cache)
    if PATH_APPLIES_EARLIER and paths:
        tree = _build(main, paths, cache)  # second pass: every *INCLUDE_PATH known from the start
    return tree
