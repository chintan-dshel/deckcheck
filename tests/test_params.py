from pathlib import Path

from deckcheck.conditions import UNKNOWN
from deckcheck.includes import resolve_tree
from deckcheck.params import collect

TORTURE = Path(__file__).parent / "torture"


def tree(tmp_path, text):
    (tmp_path / "main.k").write_bytes(text.encode("latin-1"))
    return resolve_tree(tmp_path / "main.k")


def test_torture_parameter():
    assert collect(resolve_tree(TORTURE / "parameter" / "main.k")) == {"YOUNG": 210000.0}


def test_types_pairs_and_free_format(tmp_path):
    t = tree(tmp_path, "*KEYWORD\n*PARAMETER\nI mm               1R rho        7.85E-9\nC name,steel\n*END\n")
    assert collect(t) == {"MM": 1, "RHO": 7.85e-9, "NAME": "steel"}


def test_what_cannot_be_known_is_unknown(tmp_path):
    t = tree(tmp_path, "*KEYWORD\n*PARAMETER\nR a              1.0\n*PARAMETER\nR a              2.0\n"
                       "*PARAMETER_EXPRESSION\nR b       a*2\nR c       3.5\n*PARAMETER_LOCAL\nI d                4\n*END\n")
    p = collect(t)
    assert p["A"] is UNKNOWN          # redefined with another value
    assert p["B"] is UNKNOWN          # an expression
    assert p["C"] == 3.5              # an expression that is a plain number
    assert p["D"] is UNKNOWN          # a scoped parameter
