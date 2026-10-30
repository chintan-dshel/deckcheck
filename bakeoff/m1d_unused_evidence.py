"""Verify a DC005 finding by text (spec §8): list every non-comment line in the deck's include tree, other than the
definition, where the id appears as a whole token. python -m bakeoff.m1d_unused_evidence <deck> <id> <def file:line>"""
import re
import sys
from pathlib import Path

from deckcheck.includes import resolve_tree

deck, id_, at = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
token = re.compile(rf"(?<![\w.+-]){re.escape(id_)}(?![\w.])")
hits = 0
for node in resolve_tree(deck).files:
    for n, line in enumerate(node.path.read_bytes().decode("latin-1").split("\n"), 1):
        if line.startswith(("$", "*")) or f"{node.path.name}:{n}" == at:
            continue
        if token.search(line):
            hits += 1
            if hits <= 20:
                print(f"{node.path.name}:{n}: {line.rstrip()[:100]}")
print(f"{hits} other line(s) contain {id_}")
