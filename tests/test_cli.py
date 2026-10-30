import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deckcheck.cli import main
from deckcheck.rules import check

TORTURE = Path(__file__).parent / "torture"
SEEDED = TORTURE / "seeded_mistakes" / "main.k"


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_text_output_and_exit_1(capsys, monkeypatch):
    monkeypatch.chdir(TORTURE)
    code, out, _ = run(capsys, "seeded_mistakes/main.k")
    lines = out.splitlines()
    assert code == 1
    assert lines[0] == "seeded_mistakes/main.k:3:1  error    DC004  include file 'missing_file.k' not found"
    assert any(l.startswith("seeded_mistakes/main.k:8:29  error    DC001  *PART mid refers to MAT 99") for l in lines)
    assert "Not checked:" in lines
    assert any(l.startswith("  unused MAT (DC005): main.k:3 missing include") for l in lines)


def test_summary_counts(capsys):
    ds = check(SEEDED).diagnostics
    e, w = sum(d.severity == "error" for d in ds), sum(d.severity == "warning" for d in ds)
    word = lambda n, s: f"{n} {s}{'' if n == 1 else 's'}"
    _, out, _ = run(capsys, SEEDED)
    assert f"{word(e + w, 'problem')} ({word(e, 'error')}, {word(w, 'warning')})" in out.splitlines()


def test_clean_deck_exit_0(capsys):
    code, out, _ = run(capsys, TORTURE / "base" / "main.k")
    assert code == 0 and out.startswith("No problems found")


def test_json_output(capsys):
    code, out, _ = run(capsys, "--format", "json", SEEDED)
    data = json.loads(out)
    assert code == 1 and data["version"] == 1
    d = [d for d in data["diagnostics"] if d["code"] == "DC001"][0]
    assert (d["line"], d["column"], d["end_column"], d["severity"]) == (8, 29, 31, "error")
    assert set(d) == {"file", "line", "column", "end_column", "severity", "code", "message", "related"}
    dup = [d for d in data["diagnostics"] if d["code"] == "DC002"][0]
    assert dup["related"] == [{"file": dup["file"], "line": 8, "message": "first definition"}]
    assert data["summary"] == {"errors": sum(d["severity"] == "error" for d in data["diagnostics"]),
                               "warnings": sum(d["severity"] == "warning" for d in data["diagnostics"])}
    assert {"main", "what", "reasons", "count"} == set(data["not_checked"][0])


def test_ignore_codes(capsys):
    code, out, _ = run(capsys, "--format", "json", "--ignore", "dc001", "--ignore", "DC002", "--ignore", "DC004", SEEDED)
    assert code == 0 and not [d for d in json.loads(out)["diagnostics"] if d["severity"] == "error"]
    with pytest.raises(SystemExit) as e:
        main(["--ignore", "DC999", str(SEEDED)])
    assert e.value.code == 2
    assert "DC999" in capsys.readouterr().err


def test_missing_or_folder_main_exits_2(capsys, tmp_path):
    code, out, err = run(capsys, tmp_path / "nope.k")
    assert code == 2 and out == "" and "nope.k" in err and "Traceback" not in err
    code, _, err = run(capsys, tmp_path)
    assert code == 2 and "Traceback" not in err


def test_path_on_another_drive_prints_absolute(capsys, monkeypatch):
    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")
    monkeypatch.setattr("deckcheck.cli.os.path.relpath", other_drive)
    _, out, _ = run(capsys, SEEDED)
    assert out.splitlines()[0].startswith(Path(os.path.abspath(SEEDED)).as_posix() + ":3:1")


def test_unencodable_path_does_not_crash(tmp_path):
    folder = tmp_path / "モデル"
    folder.mkdir()
    (folder / "main.k").write_text("*KEYWORD\n*INCLUDE\nmissing.k\n*END\n", encoding="latin-1")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run([sys.executable, "-m", "deckcheck", str(folder / "main.k")], capture_output=True, env=env)
    assert proc.returncode == 1 and b"Traceback" not in proc.stderr and b"DC004" in proc.stdout


def test_two_main_decks(capsys):
    code, out, _ = run(capsys, "--format", "json", SEEDED, TORTURE / "base" / "main.k")
    data = json.loads(out)
    assert code == 1 and len({n["main"] for n in data["not_checked"]}) == 2  # each main deck has its own footer
