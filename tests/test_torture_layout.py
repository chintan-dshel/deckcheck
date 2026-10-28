import tomllib
from pathlib import Path

TORTURE = Path(__file__).parent / "torture"
CASES = ["base", "free_format", "long_format", "parameter", "include_path", "comments",
         "lowercase", "tabs", "crlf", "latin1", "seeded_mistakes"]


def test_every_case_has_main_and_expected():
    for case in CASES:
        folder = TORTURE / case
        assert (folder / "main.k").is_file(), case
        expected = tomllib.loads((folder / "expected.toml").read_text(encoding="utf-8"))
        assert isinstance(expected["lsdyna_valid"], bool), case
        assert isinstance(expected["findings"], list), case


def test_byte_cases_have_their_bytes():
    assert b"\r\n" in (TORTURE / "crlf" / "main.k").read_bytes()
    assert b"Pr\xfcfplatte" in (TORTURE / "latin1" / "main.k").read_bytes()
