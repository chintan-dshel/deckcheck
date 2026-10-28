"""Write the torture cases whose bytes matter: CRLF line endings, Latin-1 titles, a blank title card.
Run once; output is committed."""
from pathlib import Path

HERE = Path(__file__).parent
base = (HERE / "base" / "main.k").read_bytes()

crlf = base.replace(b"deckcheck torture: base", b"deckcheck torture: crlf").replace(b"\n", b"\r\n")
(HERE / "crlf").mkdir(exist_ok=True)
(HERE / "crlf" / "main.k").write_bytes(crlf)

latin1 = base.replace(b"deckcheck torture: base", b"deckcheck torture: latin1").replace(b"\nplate\n", b"\nPr\xfcfplatte\n")
(HERE / "latin1").mkdir(exist_ok=True)
(HERE / "latin1" / "main.k").write_bytes(latin1)

seeded = (HERE / "seeded_mistakes" / "main.k").read_bytes()
(HERE / "crlf_seeded").mkdir(exist_ok=True)
(HERE / "crlf_seeded" / "main.k").write_bytes(seeded.replace(b"\n", b"\r\n"))
(HERE / "latin1_seeded").mkdir(exist_ok=True)
(HERE / "latin1_seeded" / "main.k").write_bytes(seeded.replace(b"\nbumper\n", b"\nSto\xdfstange f\xfcr vorn\n"))

blank = base.replace(b"deckcheck torture: base", b"deckcheck torture: blank title").replace(b"\nplate\n", b"\n\n")
(HERE / "blank_title").mkdir(exist_ok=True)
(HERE / "blank_title" / "main.k").write_bytes(blank)
