from pathlib import Path

from bakeoff.run import run_one

TORTURE = Path(__file__).parent / "torture"


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
