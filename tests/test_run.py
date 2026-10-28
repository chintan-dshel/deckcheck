from pathlib import Path

import json

from bakeoff.run import _decks, main, run_one

TORTURE = Path(__file__).parent / "torture"


def test_decks_are_named():
    named = dict(_decks(torture=True, corpus=False, tier=None))
    assert "seeded_mistakes" in named and named["seeded_mistakes"].name == "main.k"


def test_main_writes_the_name_on_every_row(tmp_path, monkeypatch):
    # The triage scripts key on row["name"]; the runner itself must write it.
    out = tmp_path / "torture.jsonl"
    monkeypatch.setattr("sys.argv", ["run", "--torture", "--out", str(out)])
    main()
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows and all(r["name"] for r in rows)
    assert {r["name"] for r in rows} >= {"base", "seeded_mistakes"}


def test_run_one_returns_probe_result_with_peak():
    r = run_one(TORTURE / "seeded_mistakes" / "main.k")
    assert len(r["findings"]) == 5 and r["peak_mb"] > 0


def test_peak_counts_the_real_interpreter_not_the_venv_launcher():
    # On Windows a venv's python.exe is a ~5 MB launcher; the interpreter that imports dynars is its child.
    r = run_one(TORTURE / "base" / "main.k")
    assert r["peak_mb"] > 15


def test_run_one_kills_at_cap():
    r = run_one(TORTURE / "base" / "main.k", cap_mb=1)
    assert r["error"].startswith("exceeded memory cap")


def test_run_one_large_output(tmp_path):
    deck = tmp_path / "many.k"
    lines = ["*KEYWORD"]
    for i in range(1, 3001):  # 3000 unused materials -> 3000 warnings, a large JSON result
        lines += ["*MAT_ELASTIC", f"{i:>10d}   7.85E-9  210000.0       0.3"]
    deck.write_text("\n".join(lines + ["*END", ""]), encoding="ascii")
    r = run_one(deck, timeout_s=300)
    assert "error" not in r and len(r["findings"]) == 3000
