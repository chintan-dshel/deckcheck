from pathlib import Path

from lsprotocol import types
from pygls.uris import from_fs_path

from deckcheck.lsp.convert import merge, to_lsp, utf16_column
from deckcheck.rules import check

TORTURE = Path(__file__).parent / "torture"


def test_ascii_column_unchanged():
    assert utf16_column("         1        99", 10, from_disk=True) == 10


def test_utf8_prefix_shifts_column():
    disk = "é,1,99".encode("utf-8").decode("latin-1")  # how M1 sees a UTF-8 file: 'Ã©,1,99'
    assert utf16_column(disk, 5, from_disk=True) == 4  # VS Code shows 'é' as one character


def test_invalid_utf8_counts_one_per_byte():
    assert utf16_column("\xe9,1,99", 3, from_disk=True) == 3  # shown as U+FFFD, one unit


def test_editor_text_counts_utf16_units():
    assert utf16_column("\U0001F600 1", 2, from_disk=False) == 3  # an emoji is two UTF-16 units


def test_to_lsp_covers_every_file_and_maps_fields():
    r = check(TORTURE / "seeded_mistakes" / "main.k")
    out = to_lsp(r, synced=lambda p: False)
    uris = {from_fs_path(str(f.path)) for f in r.tree.files}
    assert set(out) == uris
    main = out[from_fs_path(str(r.tree.files[0].path))]
    dc001 = next(d for d in main if d.code == "DC001")
    m1 = next(d for d in r.diagnostics if d.code == "DC001")
    assert dc001.range.start == types.Position(m1.line - 1, m1.start)
    assert dc001.severity == types.DiagnosticSeverity.Error and dc001.source == "deckcheck"


def _d(msg):
    return types.Diagnostic(range=types.Range(types.Position(0, 0), types.Position(0, 1)), message=msg)


def test_merge_dedupes_and_names_models():
    per_model = {"a": {"u": [_d("same"), _d("only a")]}, "b": {"u": [_d("same")]}}
    got = merge(per_model, {"a": "case_a.k", "b": "case_b.k"})["u"]
    assert [d.message for d in got] == ["same", "only a (in model case_a.k)"]
