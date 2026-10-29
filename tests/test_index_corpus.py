import tomllib
from collections import Counter
from pathlib import Path

import pytest

from bakeoff.corpus import fetch, load_manifest
from bakeoff.run import MANIFEST
from deckcheck.includes import resolve_tree
from deckcheck.index import build

pytestmark = pytest.mark.corpus
EXPECTED = {d["name"]: d for d in tomllib.loads(
    (Path(__file__).parent / "corpus" / "expected_index.toml").read_text(encoding="utf-8"))["deck"]}
SMALL = [e for e in load_manifest(MANIFEST) if e.tier == 1]


@pytest.mark.parametrize("entry", SMALL, ids=lambda e: e.name)
def test_tier1_index_matches_judged_findings(entry):
    ix = build(resolve_tree(fetch(entry)))
    want = EXPECTED.get(entry.name, {"dangling": [], "duplicates": []})
    if "dangling_counts" in want:  # many identical findings: compare counts per (kind, id, file)
        assert Counter((r.kind, r.id, r.path.name) for r in ix.dangling()) == {
            (d["kind"], d["id"], d["file"]): d["count"] for d in want["dangling_counts"]}
    else:
        assert [(r.kind, r.id, r.path.name, r.line) for r in ix.dangling()] == [
            (d["kind"], d["id"], d["file"], d["line"]) for d in want["dangling"]]
    assert [(d.kind, d.id, d.path.name, d.line) for d in ix.duplicates()] == [
        (d["kind"], d["id"], d["file"], d["line"]) for d in want["duplicates"]]


def test_icfd_parts_are_their_own_namespace():
    entry = [e for e in SMALL if "main_fsi" in e.name][0]
    ix = build(resolve_tree(fetch(entry)))
    assert ix.defs.get("ICFD_PART") and "ICFD_PART" not in {r.kind for r in ix.dangling()}
