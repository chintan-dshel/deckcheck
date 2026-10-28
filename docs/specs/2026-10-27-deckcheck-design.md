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
| Parse adapter | Wraps the parser chosen in M0. Produces a `Deck`: cards with keyword, fields, file, line and column span, and the include tree. The only module that imports the third-party parser. | M0 winner |
| Keyword schema | Data files (YAML, one per keyword family): field names, column positions, and which entity each field references (e.g. `*PART.mid → MAT`). Written by us. | nothing |
| Index | For each entity kind (part, section, material, hourglass, EOS, part set, contact): where each ID is defined and where it is referenced, across all included files. | Deck, schema |
| Rules | One function per check: takes the index (and Deck), returns a list of diagnostics. | Index, schema |
| Diagnostics | Record: file, line, column span, severity, code, message, related locations. | nothing |
| Front doors | Format diagnostics. Contain no checking logic. | Diagnostics |

The index is the central piece. All five version-1 checks, Ctrl+click, the MCP find-references tool and the M5
diff are queries on it.

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

Candidates: pydyna (`ansys-dyna-core`) and dynars. Others are excluded unless both fail.

Winning criteria, in priority order:
1. Keeps file, line and column positions for every card
2. Survives every corpus deck without crashing; unknown keywords are kept, not dropped
3. Round-trip: read then write gives an identical file
4. Handles long format, free (comma) format and `*PARAMETER`
5. Parses the vehicle model within a capped memory budget (dev laptop: 7.7 GB RAM; cap set in the plan)
6. License compatible with Apache-2.0, and actively maintained

Fallback if neither keeps positions: a thin card-splitter of our own supplies positions, and the parser supplies
field meanings.

M0 output: a written comparison (publishable on its own) and the chosen parser recorded in this spec.

## 8. Test corpus

| Tier | Decks | Stored |
|---|---|---|
| 1. Breadth | ~20–30 official LS-DYNA example decks (dynaexamples.com) across keyword families | Downloaded at test time; terms to check in M0 |
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
- Layout: `src/deckcheck/{parse/, schema/, index.py, rules/, diagnostics.py, cli.py}`, `tests/{rules/, torture/,
  corpus/manifest.toml}`, `editors/vscode/` (M2), `docs/`.
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

- **M0 done:** both candidates run on all three tiers; the comparison against the six criteria is written up;
  the parser choice is recorded here; the terms for the example decks and CCSA are checked and recorded.
- **M1 done:**
  - DC001–DC005 each catch their seeded mistake.
  - Zero unexplained diagnostics on the full corpus.
  - `pip install` works from a clean environment.
  - The CLI's text and JSON output are documented in the README.
  - The package is published to PyPI only with Chintan's explicit yes.

## 12. Open questions

- Terms for the LS-DYNA example decks and CCSA models (resolved in M0).
- License of pydyna's keyword data, if reused for the schema (resolved in M0).
- Memory cap value for the corpus run (set in the plan).
