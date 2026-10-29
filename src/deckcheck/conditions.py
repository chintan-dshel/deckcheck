"""Evaluate pydyna's card conditions and lengths (extracted as source text by tools/extract_keyword_data.py)
without running code: a small evaluator over a whitelisted subset of Python expressions. Undecidable -> UNKNOWN."""
import ast
import functools
import math


class _Unknown:
    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN = _Unknown()

FUNCS = {("abs",): abs, ("int",): int, ("max",): max, ("min",): min, ("math", "ceil"): math.ceil}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}
_CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
        ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b}


class Scope:
    def __init__(self, parent: "Scope | None" = None):
        self.values: dict[str, object] = {}
        self.parent = parent


def _chain(node) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        inner = _chain(node.value)
        return inner + (node.attr,) if inner else None
    return None


def _is_field(chain) -> bool:
    return chain is not None and (len(chain) == 2 and chain[0] == "self" and chain[1] != "parent"
                                  or len(chain) == 3 and chain[:2] == ("self", "parent"))


def _column(n) -> str | None:
    """`self.<table>['<col>'].any()`: pydyna asks whether any row has the column set. The field reader evaluates
    conditions row by row, as LS-DYNA reads each element, so it means: this row's column is set."""
    if (isinstance(n, ast.Call) and not n.args and not n.keywords and isinstance(n.func, ast.Attribute)
            and n.func.attr == "any" and isinstance(n.func.value, ast.Subscript)):
        sub = n.func.value
        chain = _chain(sub.value)
        if chain and len(chain) == 2 and chain[0] == "self" and isinstance(sub.slice, ast.Constant) \
                and isinstance(sub.slice.value, str):
            return sub.slice.value
    return None


def _allowed(n) -> bool:
    if _column(n):
        return True
    if isinstance(n, ast.Constant):
        return True
    if isinstance(n, (ast.List, ast.Tuple)):
        return all(map(_allowed, n.elts))
    if isinstance(n, (ast.Attribute, ast.Name)):
        return _is_field(_chain(n))
    if isinstance(n, ast.BoolOp):
        return all(map(_allowed, n.values))
    if isinstance(n, ast.UnaryOp):
        return isinstance(n.op, (ast.Not, ast.USub, ast.UAdd)) and _allowed(n.operand)
    if isinstance(n, ast.BinOp):
        return type(n.op) in _BIN and _allowed(n.left) and _allowed(n.right)
    if isinstance(n, ast.Compare):
        return all(type(op) in _CMP for op in n.ops) and _allowed(n.left) and all(map(_allowed, n.comparators))
    if isinstance(n, ast.IfExp):
        return _allowed(n.test) and _allowed(n.body) and _allowed(n.orelse)
    if isinstance(n, ast.Call):
        return _chain(n.func) in FUNCS and not n.keywords and all(map(_allowed, n.args))
    return False


@functools.cache
def compile_expr(text: str) -> ast.Expression | None:
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    return tree if _allowed(tree.body) else None


def names_in(text: str) -> frozenset[str]:
    tree = compile_expr(text)
    if tree is None:
        return frozenset()
    columns = {c for n in ast.walk(tree) if (c := _column(n))}
    tables = {_chain(n.func.value.value)[1] for n in ast.walk(tree) if _column(n)}
    fields = {c[-1] for n in ast.walk(tree) if _is_field(c := _chain(n))}
    return frozenset(columns | (fields - tables))


def evaluate(tree: ast.Expression, scope: Scope) -> object:
    try:
        return _eval(tree.body, scope)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return UNKNOWN


def _eval(n, s: Scope) -> object:
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, (ast.List, ast.Tuple)):
        items = [_eval(e, s) for e in n.elts]
        return UNKNOWN if any(i is UNKNOWN for i in items) else items
    if isinstance(n, (ast.Attribute, ast.Name)):
        chain = _chain(n)
        scope = s if len(chain) == 2 else s.parent
        return UNKNOWN if scope is None else scope.values.get(chain[-1], UNKNOWN)
    if isinstance(n, ast.BoolOp):
        result, unknown = None, False
        for v in n.values:
            r = _eval(v, s)
            if r is UNKNOWN:
                unknown = True
            elif isinstance(n.op, ast.And) and not r:
                return r
            elif isinstance(n.op, ast.Or) and r:
                return r
            else:
                result = r
        return UNKNOWN if unknown else result
    if isinstance(n, ast.UnaryOp):
        v = _eval(n.operand, s)
        if v is UNKNOWN:
            return UNKNOWN
        return not v if isinstance(n.op, ast.Not) else -v if isinstance(n.op, ast.USub) else +v
    if isinstance(n, ast.BinOp):
        a, b = _eval(n.left, s), _eval(n.right, s)
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
            return UNKNOWN  # numbers only: a str field times a count would build a huge string
        return _BIN[type(n.op)](a, b)
    if isinstance(n, ast.Compare):
        left = _eval(n.left, s)
        for op, comp in zip(n.ops, n.comparators):
            right = _eval(comp, s)
            if left is UNKNOWN or right is UNKNOWN:
                return UNKNOWN
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(n, ast.IfExp):
        t = _eval(n.test, s)
        return UNKNOWN if t is UNKNOWN else _eval(n.body if t else n.orelse, s)
    if col := _column(n):
        v = s.values.get(col, UNKNOWN)
        return UNKNOWN if v is UNKNOWN else bool(v)
    args = [_eval(a, s) for a in n.args]  # ast.Call: _allowed admitted only FUNCS
    return UNKNOWN if any(a is UNKNOWN for a in args) else FUNCS[_chain(n.func)](*args)
