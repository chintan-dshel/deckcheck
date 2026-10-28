"""Write the torture cases whose bytes matter: CRLF line endings and a Latin-1 title. Run once; output is committed."""
from pathlib import Path

HERE = Path(__file__).parent
base = (HERE / "base" / "main.k").read_bytes()

crlf = base.replace(b"deckcheck torture: base", b"deckcheck torture: crlf").replace(b"\n", b"\r\n")
(HERE / "crlf").mkdir(exist_ok=True)
(HERE / "crlf" / "main.k").write_bytes(crlf)

latin1 = base.replace(b"deckcheck torture: base", b"deckcheck torture: latin1").replace(b"\nplate\n", b"\nPr\xfcfplatte\n")
(HERE / "latin1").mkdir(exist_ok=True)
(HERE / "latin1" / "main.k").write_bytes(latin1)
