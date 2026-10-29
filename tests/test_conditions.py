import pytest

from deckcheck.conditions import UNKNOWN, Scope, compile_expr, evaluate, names_in
from deckcheck.keywords import load


def run(text, parent=None, **values):
    scope = Scope(parent)
    scope.values.update(values)
    return evaluate(compile_expr(text), scope)


def test_section_shell_forms():
    assert run("self.icomp == 1", icomp=1) is True
    assert run("2 if self.nip == 0 else self.nip", nip=0) == 2
    assert run("2 if self.nip == 0 else self.nip", nip=5) == 5
    assert run("self.elform in [101, 102, 103, 104, 105]", elform=2) is False


def test_parent_and_functions():
    parent = Scope()
    parent.values["nhisv"] = 3
    assert run("self.parent.nhisv", parent) == 3
    assert run("math.ceil((self.nr + self.pr + 1) / 4)", nr=4, pr=2) == 2
    assert run("abs(self.dof) in [9, 10, 11] or self.vad == 4", dof=-10, vad=0) is True


def test_unknown_propagates_but_short_circuits():
    assert run("self.missing == 1") is UNKNOWN
    assert run("self.a > 0 and self.missing", a=0) is False
    assert run("self.a > 0 or self.missing", a=1) is True
    assert run("self.a > 0 and self.missing", a=1) is UNKNOWN
    assert run("self.a > 0", a=None) is UNKNOWN  # None > 0 is a TypeError: undecided, not False


def test_outside_the_grammar_is_refused():
    for text in ["self._cards[1].has_nondefault_values()", "__import__('os')", "self.elements['n5'].sum()",
                 "(lambda: 1)()", "self.a.b.c", "?"]:
        assert compile_expr(text) is None, text


def test_names_in():
    assert names_in("2 if self.nip == 0 else self.nip") == {"nip"}
    assert names_in("self.parent.large == 1") == {"large"}


def test_extracted_expressions_compile_or_are_known_exceptions():
    def walk(cards):
        for c in cards:
            yield c
            yield from walk(c.get("cards", []))
    refused = {t for k in load()["keywords"].values() for c in walk(k["cards"])
               for t in (c.get("when"), c.get("length")) if t and compile_expr(t) is None}
    # every refused text reads another card's state or a pandas frame: undecidable from field values
    assert all(any(m in t for m in ("_cards[", ".any()", ".empty", "has_nondefault", ".iloc", "?")) for t in refused), refused
    assert len(refused) <= 30


def test_column_any_reads_the_current_row():
    # pydyna's whole-table test; LS-DYNA decides per element, and the field reader evaluates it per row
    assert run("self.elements['n5'].any()", n5=7) is True
    assert run("self.elements['n5'].any()", n5=None) is False
    assert run("self.elements['n5'].any()", n5=0) is False
    assert names_in("self.elements['n5'].any()") == {"n5"}
