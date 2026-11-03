# M2c: navigation in VS Code

Plan: `docs/plans/2026-11-01-m2c-navigation.md`. Spec: `docs/specs/2026-10-30-m2-vscode-design.md` §5.2–5.6, §11.
Branch `m2c`, 2026-11-03.

## What it delivers

Once a model has been checked, across all its include files:
- **Hover** on a field: name, columns, type, default, the value as read (`&m = 1` after a parameter), and what an id
  resolves to (`mid → MAT 1, *MAT_ELASTIC at mat.k:3`), with the `*INCLUDE_TRANSFORM` offset when there is one. On a
  definition: its use count, other definitions of the same id, and which uses deckcheck can't place. On a keyword
  line: the keyword as deckcheck resolved it. No text from the keyword manual.
- **Go to definition** and **find references**, including a part set id that falls back to the part, ids shifted by
  a transform, and a file shared by two models (both models' answers, without duplicates).
- **Outline**: one entry per keyword block, named by keyword, id and title; a block defining many ids says how many
  cards it has.
- **Field hints** (hold Ctrl+Alt) for the visible range, at most 2,000.
- **Insert field ruler**: a `$#` comment naming the columns above a fixed-column card.

The VS Code client needed no change: `vscode-languageclient` forwards the new requests as they are (its middleware
filters only the sync notifications). The integration test `hoverAndDefinitionAcrossIncludes` proves it.

## How it stays fast

- After each check the worker turns the index's dicts into flat arrays (`navigate.NavIndex`): ids as int64 bytes
  searched with `bytes.find`, no Python object per id. The Yaris has 3,013,004 definitions and 6,314,549 references.
- A request re-reads only the keyword block under the cursor. Uniform tables (`*NODE`, `*ELEMENT_SHELL`, `*PART`) are
  read from the cursor's row alone, at any depth; other blocks up to 2,000 cards (D5).
- A request never waits. It answers only if the file's parse is still the one the last check made (identity, not
  time), and returns nothing while the worker is freeing parses (a non-blocking lock).

## Gates

Measured on the CCSA Toyota Yaris (161 MB model, 169 MB largest include) after its check, unless stated.

| Gate (plan D7) | Limit | Measured |
|---|---|---|
| Hover on the first shell of the most-used part | 100 ms | 13 ms |
| Go to definition there | 100 ms | 8 ms |
| References to the most-used part (37,158 uses), in VS Code | 1 s | 660 ms, 580 ms (two harm runs) |
| The same, through the Python test client | 1.5 s (see rulings) | 1,024 ms |
| Outline of a 56-keyword include, first and repeated | 1 s / 50 ms | 18 ms / 4 ms |
| Outline of a generated 10,000-keyword file | 1 s | 0.42 s (`*DEFINE_CURVE`, 20 points each), 0.14 s (`*PART`) |
| Hints for 61 lines, Yaris shells | 100 ms | 16–19 ms (610 hints) |
| Hints for lines 1,000,000–1,000,060 of a generated 1.5 M-node block | 100 ms | 2.7 ms first, 1.1 ms after |
| Reading at the 2,000-card limit of a non-uniform block | 50 ms | 8 ms |
| Hostile files (1 MB line, binary, NUL bytes): every feature | 1 s each, server survives | pass |

Memory, Yaris after its check with the parse kept: 809 MB without the navigation index, 971 MB with it (+162 MB, the
plan estimated about 180 MB). Peak, before the check's own index is freed: 1,157 → 1,322 MB, under the 2,048 MB
budget. The Yaris check itself: 64.3 s before M2c, 65.6 s after (+2 %; see the first ruling).

### Harm gate re-run (spec §10.1), alone, with the features on

| Gate | Pass rule | M2b | M2c |
|---|---|---|---|
| Open the small deck, on vs off | ≤ 10 % or ≤ 20 ms | 42 vs 41 ms | 44 vs 42 ms; 43 vs 39 ms |
| Open the Yaris main deck, idle | ≤ 10 % or ≤ 20 ms | 47 vs 41 ms | 48 vs 47 ms; 48 vs 43 ms |
| Open the 169 MB include, idle, paired median difference | ≤ 10 % or ≤ 20 ms | −12 ms | **+254 ms on 1,180 ms (fail)**; −143 ms on 1,437 ms; +49 ms on 1,384 ms |
| An editor command during a Yaris check | < 100 ms | 1.5 ms | 1.3 ms; 1.1 ms |
| Hover during a Yaris check (new) | < 100 ms | n/a | 14 ms; 17 ms |

The 169 MB line failed once. The first full run measured +254 ms. The same test run alone measured −143 ms, and a
second full run measured +49 ms. Single opens of that file range from 0.9 to 2.4 s with deckcheck on or off. Nothing
M2c adds runs while that file opens: it is never synced, so VS Code sends no requests for it, and the server is
freshly resumed and idle. I read the failure as the noise this gate's pairing was built against, not as a cost; two of
three runs pass. A further full run would settle it if you want more than that.

## Rulings made during the build (cost if wrong)

1. `index.target()` is a NamedTuple wrapper over a plain-tuple core, and the index skips blank fields before
   calling it. The plan's version cost 13 % of a Yaris check; now +2 %. Cost: none while one function serves both.
2. The outline lists `*KEYWORD` as its first entry. The plan's test skipped it while its count of 10,002 counted it.
   Cost: one extra row at the top of each outline.
3. The drop set is taken under the read lock too. Otherwise a request could answer from a changed file's old parse.
   Cost: the worker waits milliseconds for a request in flight.
4. Navigation docs are in the extension README and one sentence in the root README. The manual and roadmap exist only
   on the unmerged `docs-manual` branch, so their navigation section and "M2 done" wait for that merge (backlog).
5. References are gated in VS Code at 1 s. The Python test client adds about half a second parsing 37,158 locations,
   so its own ceiling is 1.5 s. Cost: another LSP editor slower than VS Code may take over 1 s on a part with ~40k uses.
6. To meet that, a location's URI is built once per file and ASCII lines skip the UTF-16 conversion.
7. Step 3 of the plan (navigation on the generated 300 MB single-file mesh) was not run as written: that file is never
   synced, so its parse is released after its check (an M2b ruling) and navigation there answers nothing by design.
   The reading deep in a 1.5 M-node block was measured directly instead. Backlog item.
8. Small fixes to the plan's test code, none to behaviour: LSP types built with keyword arguments, replies read as
   dict or object, the hover's Markdown read through its value.

## Decisions D1–D8

As proposed in the plan and approved by Chintan on 2026-11-03: answers from the last check only (D1, the outline of a
synced file up to 2 MB excepted), nothing before a model's first check (D2), "Outline off" past 10,000 keywords in the
outline itself (D3, amends spec §5.5), `navigate.py` instead of `Index.at`/`Index.uses` (D4, amends spec §4.3), nothing
deep in non-uniform blocks (D5), uncapped references (D6), the timing gates above (D7), the ruler on fixed-column cards
of synced files only (D8).

## For M3

`deckcheck/navigate.py` has no LSP types: `build_nav`, `NavIndex.definitions/uses/owner`, `block_at`,
`fields_between`, `hit`, `subject`, `explain`, `outline`, `hints` and `ruler` are what an MCP server's lookups need.
