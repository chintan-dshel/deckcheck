"""For each tier-1 deck with dynars Error findings, ask LS-DYNA whether its input phase accepts the deck.

Runs on a scratch copy of the documentation folder; stops LS-DYNA as soon as it prints 'initialization completed'
(input accepted) or 'E r r o r   t e r m i n a t i o n' (input rejected). Writes JSON lines to argv[1].
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

EXE = (r"C:\Program Files\LS-DYNA Suite R16.1 Student\lsdyna"
       r"\ls-dyna_smp_d_R16.1_180-gd50332dbe5_winx64_ifort190_sse2_studentversion.exe")
COPY = Path(r"C:\Users\DELL\AppData\Local\Temp\claude\d--AI-Projects\735ac84a-ef37-45b5-80ba-edf40fda256d\scratchpad\docs_copy")
RESULTS = Path(r"D:\AI_Projects\deckcheck\bakeoff\results\corpus_tier1.jsonl")


def ask(deck: Path, timeout_s: float = 600) -> tuple[str, str]:
    log = deck.parent / f"{deck.stem}.oracle.txt"
    with open(log, "w") as out:
        proc = subprocess.Popen([EXE, f"i={deck.name}", "ncpu=1"], cwd=deck.parent, stdout=out,
                                stderr=subprocess.STDOUT, env={**os.environ, "LSTC_LICENSE": "Ansys"})
    start, verdict = time.monotonic(), "timeout"
    while proc.poll() is None and time.monotonic() - start < timeout_s:
        text = log.read_text(encoding="latin-1")
        if "initialization completed" in text:
            verdict = "accepted"
            break
        if "E r r o r   t e r m i n a t i o n" in text:
            verdict = "rejected"
            break
        time.sleep(0.5)
    if proc.poll() is None:
        for c in psutil.Process(proc.pid).children(recursive=True):
            c.kill()
        proc.kill()
        proc.wait()
    text = log.read_text(encoding="latin-1")
    if verdict == "timeout" and "initialization completed" in text:
        verdict = "accepted"
    elif verdict == "timeout" and "E r r o r   t e r m i n a t i o n" in text:
        verdict = "rejected"
    errors = [ln.strip() for i, ln in enumerate(text.splitlines()) if "*** Error" in ln]
    return verdict, "; ".join(dict.fromkeys(errors))[:400]


with open(sys.argv[1], "w", encoding="utf-8") as f:
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if not any(x["severity"] == "Error" for x in r["findings"]):
            continue
        rel = r["deck"].split("documentation\\", 1)[1]
        verdict, errors = ask(COPY / rel)
        row = {"name": r["name"], "lsdyna_input": verdict, "lsdyna_errors": errors}
        f.write(json.dumps(row) + "\n")
        f.flush()
        print(r["name"], verdict, errors[:150], flush=True)
