"""Spec §5: DC005 reports a kind only once every field that could refer to it is linked. The name patterns are a
heuristic lower bound (docs/plans/2026-10-29-m1d-checks-cli.md, Task 5); each hit is decided by hand."""
import re

from deckcheck.coverage import DC005_KINDS, dc005_audit
from deckcheck.definers import definers
from deckcheck.keywords import layout, load, walk_cards

LOOKALIKE = {"MAT": r"^(mid|mat|mid\d+|mids|matid)$", "SECTION": r"^(secid|secid\d+)$", "HOURGLASS": r"^hgid$"}


def open_fields() -> list[tuple[str, str, str]]:
    audited = {(e["keyword"], e["field"], e["kind"]) for e in dc005_audit()}
    out = []
    for key in sorted(load()["keywords"]):
        own = {k for k, _ in definers().get(key, ())}
        for kind in DC005_KINDS:
            if kind in own:
                continue
            for card in walk_cards(layout(key)["cards"]):
                for f in card.get("fields", []):
                    if (re.match(LOOKALIKE[kind], f["name"]) and "link" not in f and "link_by" not in f
                            and (key, f["name"], kind) not in audited):
                        out.append((key, f["name"], kind))
    return out


def test_every_lookalike_field_is_linked_or_audited():
    assert open_fields() == []


def test_audit_entries_are_well_formed():
    for e in dc005_audit():
        assert e["kind"] in DC005_KINDS and e["verdict"] in ("namespace", "undecided") and e["reason"], e
