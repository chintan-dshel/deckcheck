"""What deckcheck could not check in a run, and why (spec §5: never a diagnostic; §6: the "Not checked" footer)."""
import functools
import tomllib
from importlib import resources

from deckcheck.diagnostics import NotChecked
from deckcheck.includes import Tree
from deckcheck.index import STRUCTURAL, Index

DC005_KINDS = ("MAT", "SECTION", "HOURGLASS")  # spec §5: the kinds whose every referring field is audited
SHOWN = 3


@functools.cache
def dc005_audit() -> list[dict]:
    text = resources.files("deckcheck.data").joinpath("dc005_audit.toml").read_text(encoding="utf-8")
    return tomllib.loads(text).get("field", [])


def unknown_keywords(tree: Tree) -> list[tuple[str, str]]:
    """(file:line, name) of every block the keyword data doesn't cover: it passes through unchecked (spec §4)."""
    return [(f"{node.path.name}:{b.line}", b.name) for node in tree.files for b in node.source.blocks
            if b.resolved is None and b.name not in STRUCTURAL and not b.name.startswith(("INCLUDE", "PARAMETER"))]


def dc005_silent(tree: Tree, ix: Index) -> dict[str, str]:
    """Kinds DC005 must stay silent on, each with the first reason: a use deckcheck can't see would make a used
    definition look unused."""
    why: dict[str, str] = {}
    unknown = unknown_keywords(tree)
    present = {b.resolved.name for node in tree.files for b in node.source.blocks if b.resolved}
    for kind in DC005_KINDS:
        if ix.blind:
            why[kind] = sorted(ix.blind)[0]
        elif ix.failures:
            fi, line, text = ix.failures[0]
            why[kind] = f"{tree.files[fi].path.name}:{line} {text}"
        elif kind in ix.uncertain_uses:
            why[kind] = sorted(ix.uncertain_uses[kind])[0]
        elif kind in ix.uncertain_defs:
            why[kind] = sorted(ix.uncertain_defs[kind])[0]
        elif unknown:
            where, name = unknown[0]
            why[kind] = f"{where} *{name}: a keyword deckcheck doesn't know may refer to it"
        else:
            for entry in dc005_audit():
                if entry["kind"] == kind and entry["verdict"] == "undecided" and entry["keyword"] in present:
                    why[kind] = f"*{entry['keyword']} {entry['field']} may refer to it (not yet audited)"
                    break
    return why


def _item(what: str, reasons: list[str]) -> NotChecked:
    return NotChecked(what, tuple(reasons[:SHOWN]), len(reasons))


def not_checked(tree: Tree, ix: Index) -> list[NotChecked]:
    out = []
    if ix.blind:
        out.append(_item("all references (DC001, DC006)", sorted(ix.blind)))
    for kind in sorted(ix.uncertain_defs):
        out.append(_item(f"references to {kind} (DC001, DC006)", sorted(ix.uncertain_defs[kind])))
    unread = [f"{tree.files[fi].path.name}:{p.line} {p.detail}" for fi, p in ix.problems if p.kind == "unread"]
    if unread:
        out.append(_item("blocks read only in part", unread))
    unknown = unknown_keywords(tree)
    if unknown:
        out.append(_item("keywords deckcheck doesn't know (passed through)", [f"{w} *{n}" for w, n in unknown]))
    for kind, why in dc005_silent(tree, ix).items():
        out.append(_item(f"unused {kind} (DC005)", [why]))
    out.append(_item("unused definitions of other kinds (DC005)", [f"checked for {', '.join(DC005_KINDS)} only"]))
    return out
