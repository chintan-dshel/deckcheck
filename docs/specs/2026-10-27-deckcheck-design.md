# deckcheck — design spec

Date: 2026-10-27 · Owner: Chintan Shelat · Status: awaiting review
Living report: https://claude.ai/artifact/A1dTFKALfhzDWuxSnqUGKS

## 1. Purpose

deckcheck is an open-source linter for LS-DYNA keyword decks (`.k`, `.key`, `.dyn`). It finds structural
mistakes before the solver runs, through three front doors on one engine: a command line (M1), a VS Code
extension (M2) and an MCP server for AI agents (M3).

The goal is adoption by other analysts. Install counts and real users are the measure of success, not the
number of checks.

## 2. Context and non-goals

- Open parsers already exist (pydyna, dynars, dynakw, lsdyna-mesh-reader, lsdyna-parser). deckcheck builds on
  one of them and never writes a new full parser.
- **Decision 2026-10-28 (option A): build on dynars.** Reconnaissance found dynars (MIT, v1.1.0) already ships
  validation rules with `file:line` findings — `references_resolve`, `duplicate_ids`, `include_missing`,
  `unreferenced_entities` — plus byte-preserving `set_field` and a keyword library generated from pydyna's field
  database. A smoke test caught all four seeded mistakes. deckcheck is therefore the front doors for LS-DYNA deck
  checking, plus the checks and position accuracy dynars lacks — not a second rules engine.
- dynars risks: single maintainer, 2 stars, created July 2026, last commit 15 Aug 2026. Mitigation: the adapter
  boundary isolates it; MIT allows a fork; pydyna is the fallback parser.
- Smoke-test defects deckcheck must correct: `include_missing` reports line 0; `references_resolve` reported a
  comment line rather than the `*PART` line; paths carry a Windows `\\?\` prefix; `deck.parts()` collapses
  duplicate ids.
- No editor tooling, language server or agent interface for LS-DYNA decks exists. That is the gap.
- Non-goals for version 1: physics checks (units, timestep, hourglass, contact defaults), editing decks, running
  the solver, any GUI beyond the editor.
- Legal: the name and branding never use "LS-DYNA" (Ansys trademark), only "for LS-DYNA" descriptively. Keyword
  documentation is written by us or taken from data whose license allows reuse; the keyword manual is never
  copied.

## 3. Bracketing (version 1)

| | |
|---|---|
| Ceiling | Hover documentation and checks for every keyword in the manual, as LS-PrePost does |
| Target | Correct cross-reference and column checks for the ~30 keywords that make up most crash models; other keywords pass through untouched |
| Floor | Syntax highlighting only (what the existing Vim plugin does) |
| Gap to close | Zero false alarms on the real corpus (section 8) while catching every seeded mistake |

## 4. Architecture

```
deck files ─► parse adapter ─► Deck ─► index ─► rules ─► diagnostics ─► front doors
                                         ▲        ▲                     (CLI, VS Code, MCP)
                                    keyword schema (data)
```

| Unit | Does | Depends on |
|---|---|---|
| Adapter (`engine/`) | The only module that imports dynars. Runs dynars' parse and built-in rules and maps each `Finding` to a deckcheck diagnostic: stable code, normalized path, corrected line. | dynars |
| Position layer | Our own light card-splitter: for each keyword block, the line of each data card and the column span of each field (comments and `$#` rulers skipped). Corrects dynars' line numbers and gives field-level spans for squiggles. Not a parser: it never interprets values. | file text |
| Own rules | Checks dynars lacks: DC003 column/format, DC004's circular-include half. Same diagnostic output. | position layer, dynars deck |
| Keyword data | dynars' built-in library (generated from pydyna's MIT field database). Our own YAML schema only for keywords it lacks, registered through `register_schema`. | dynars |
| Diagnostics | Record: file, line, column span, severity, code, message, related locations. | nothing |
| Front doors | Format diagnostics. Contain no checking logic. | Diagnostics |

dynars' deck plays the role of the index: references, definitions and `set_field` all come from it. The diagram
above is the logical flow; in code, "parse adapter + index + most rules" is the adapter over dynars.

| Code | Source |
|---|---|
| DC001 | dynars `references_resolve` |
| DC002 | dynars `duplicate_ids` |
| DC003 | deckcheck (position layer) |
| DC004 | dynars `include_missing` (missing file) + deckcheck (circular include) |
| DC005 | dynars `unreferenced_entities` |

Error handling:
- A card that won't parse produces one diagnostic, and the run continues.
- A keyword not in the schema passes through silently. This is the main defence against false alarms.
- A missing include file is reported (DC004), and the rest of the deck is still checked.

## 5. Version 1 checks

| Code | Check | Severity |
|---|---|---|
| DC001 | Dangling reference: a field points at an ID that is not defined (e.g. `*PART` material 99, no `*MAT 99`) | error |
| DC002 | Duplicate ID: two definitions of the same entity kind with the same ID | error |
| DC003 | Column or format problem: a value overflows its field, or fixed and free format are mixed within a card | warning |
| DC004 | `*INCLUDE` problem: a missing file or a circular include | error |
| DC005 | Unused definition: a material, section or similar that nothing references | warning |

Users can suppress a code with `--ignore DC005` (repeatable) in M1. Inline suppression comments and a config
file come in M4.

## 6. Front doors

- **M1, command line:** `deckcheck model.k` prints `file:line  severity  code  message`. Exit code is non-zero on
  errors, for CI. `--format json` gives machine-readable output.
- **M2, VS Code:** a Python language server (pygls) behind a thin TypeScript client. Diagnostics as squiggles,
  hover over field names, go-to-definition on IDs across includes. Published to the VS Code Marketplace and
  Open VSX.
- **M3, MCP server:** tools `lint`, `explain_keyword`, `find_references`, `get_card` and `set_field`. `set_field`
  re-runs the linter and refuses any edit that adds an error.

M2 and M3 designs are detailed in their own specs when reached. This spec binds M0 and M1.

## 7. M0 parser bake-off

After the option A decision, M0's question is no longer "which parser" but **"can deckcheck stand on dynars?"**
pydyna is measured only as the fallback.

dynars passes M0 when, on the full corpus:
1. It parses every deck without crashing, within the memory cap.
2. Its four rules produce zero unexplained findings (each finding is either a real defect in that deck,
   recorded, or a dynars false alarm, counted).
3. Every finding's line, after our correction, points at the right keyword block.
4. `set_field` round-trip: parse, write without edits → byte-identical; one edit → only that field's bytes differ.
5. It handles long format, free (comma) format and `*PARAMETER` in the torture decks.

If dynars fails 1 or 2 on decks that matter (VIVA+ or the vehicle model), stop and return to option B with
pydyna; that is a spec change, decided with Chintan.

M0 output: a written assessment (publishable on its own), the false-alarm count per rule, and the go/no-go
recorded in this spec.

**M0 result (2026-10-28): NO-GO for option A.**
- dynars' parser and edits mostly pass (criteria 1 and 4), with two parser defects: a blank-title `*PART` is
  dropped, and `*PART_INERTIA` is not indexed.
- Its reference rules and include resolution fail: 62 of 68 errors are false, and VIVA+ loads 2 of 18 files
  because `*INCLUDE_PATH` is ignored.
- The Yaris (CCSA) ran with 0 errors, but it could not be refereed by LS-DYNA Student (too large).
- Recommended route B1: dynars parser plus deckcheck's own reference and position layer.

See `docs/m0-assessment.md`. Route choice pending Chintan.

## 8. Test corpus

| Tier | Decks | Stored |
|---|---|---|
| 1. Breadth | ~20–30 official LS-DYNA example decks across keyword families. As run in M0: 35 decks from the LS-DYNA Student install's `documentation/` folder (dynaexamples.com returned 503), read in place | Local only; never committed (see `docs/corpus-terms.md`) |
| 2. Real-world | VIVA+ human body model (LGPL v3), plus one CCSA/NCAC vehicle model | Downloaded at test time; CCSA terms to check in M0 |
| 3. Torture | ~10 tiny decks, one quirk each: long format, free format, `*PARAMETER`, `*INCLUDE_PATH`, odd comments, tabs | Ours, committed |

External decks are listed in `tests/corpus/manifest.toml` with URL and sha256, and never committed. A changed
upstream deck fails the hash check instead of being tested silently.

Tests:
- Each rule has a tiny deck containing its mistake, which it must catch.
- Each rule must report zero diagnostics on every corpus deck, unless the finding is verified as a real defect
  in that deck and recorded as an expected finding.

## 9. Project setup

- Location `D:\AI_Projects\deckcheck`, local git. A public GitHub repo at the M1 release, only with Chintan's
  explicit yes.
- License: Apache-2.0 (explicit patent grant helps corporate adoption).
- Python core. Packaging via `pyproject.toml`; `pip install deckcheck` gives the core and CLI, with extras
  `deckcheck[lsp]` (M2) and `deckcheck[mcp]` (M3).
- Layout: `src/deckcheck/{engine.py, positions.py, rules/, diagnostics.py, cli.py}`, `tests/{rules/, torture/,
  corpus/manifest.toml}`, `bakeoff/` (M0 measurement scripts and results), `editors/vscode/` (M2), `docs/`.
- CI (GitHub Actions): a fast job on every push (rule and torture tests); a corpus job nightly or on demand
  (download, hash check, zero-false-alarm gate). Run locally with a memory cap.
- CONTRIBUTING.md centres on "add a keyword = add rows to a schema file".
- Later, not in M1: SARIF output for inline pull-request annotations.

## 10. Roadmap and stop points

| # | Milestone | If stopped here |
|---|---|---|
| M0 | Parser bake-off (2–3 days) | Published comparison of open parsers |
| M1 | Core and command line (~2 weeks) | Tool on PyPI that runs in CI — minimum worthwhile stop |
| M2 | VS Code extension (2–3 weeks) | First LS-DYNA tooling in VS Code |
| M3 | MCP server (~1 week) | All three front doors on one core — best stop |
| M4 | Model-quality checks (3–4 weeks) | Senior-review checks automated |
| M5 | Model tree and semantic diff (3–4 weeks) | Daily-use deck diff |
| M6 | Second solver, OpenRadioss (4–6 weeks) | Cross-solver checks |
| M7 | Rule packs (open-ended) | Company guideline packs |

## 11. Completion criteria

- **M0 done:** dynars runs on all three tiers; each of the five pass criteria in section 7 is measured and
  written up; the go/no-go is recorded here; the terms for the example decks and CCSA are checked and recorded.
- **M1 done:**
  - DC001–DC005 each catch their seeded mistake.
  - Zero unexplained diagnostics on the full corpus.
  - `pip install` works from a clean environment.
  - The CLI's text and JSON output are documented in the README.
  - The package is published to PyPI only with Chintan's explicit yes.

## 12. Open questions

- Terms for the LS-DYNA example decks and CCSA models (resolved in M0).
- License of pydyna's keyword data: resolved, MIT (pydyna is MIT; dynars' library is generated from it).
- M1 estimate drops from ~2 weeks to ~1 week if dynars passes M0 (revisit in the M1 plan).
- Memory cap value for the corpus run (set in the plan).
