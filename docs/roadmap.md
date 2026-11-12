# deckcheck roadmap

deckcheck is a work in progress. Version 0.1.0 checks a deck's structure from the command line and inside VS Code, and
navigates a model in VS Code; the next steps add an interface for AI assistants and model-quality checks. This page
says what works today, what comes next, and how each step is decided. It has no dates: each milestone ships when it
passes its own tests and measurements.

## Where it stands

| Milestone | What you get | Status |
|---|---|---|
| M0. Parser study | A measured comparison of the open parsers for keyword decks; deckcheck reads decks with its own reader | done |
| M1. Core and command line | `deckcheck main.k`: seven checks across the whole model, text or JSON output, exit codes for CI | done |
| M2. VS Code extension | Squiggles and the Problems panel for the whole model, live on small models, on save or click on big ones | done |
| M3. AI assistant interface | deckcheck's checks and lookups for AI coding assistants, through the Model Context Protocol | planned |
| M4. Model-quality checks | Checks a senior analyst does by eye; suppression of single findings | planned |
| M5. Model tree and deck diff | A browsable model tree, and a diff that says what changed in the model, not just in the text | planned |
| M6. Second solver | The same checks for OpenRadioss decks | planned |
| M7. Rule packs | Team and company conventions as optional sets of rules | planned |

## What works today (0.1.0)

Install the command line with `pip install deckcheck`, and the extension from the VS Code Marketplace or Open VSX
(search for **deckcheck**).

**Checks** (the same in the command line and the editor):
- References to ids that are never defined, and required references left blank or 0 (DC001).
- The same id defined twice (DC002).
- Values of the wrong type for their field, tabs in cards, cards past the end of a keyword, definitions with a blank
  or 0 id (DC003).
- Include files that can't be found, and includes that include themselves (DC004).
- Materials, sections and hourglass controls that nothing uses (DC005).
- References LS-DYNA accepts without checking, to ids that don't exist, so they have no effect (DC006).
- A "Not checked" list wherever deckcheck can't see everything a check needs, instead of a guess.

**Command line:** follows every `*INCLUDE` and `*INCLUDE_PATH` from the main deck, prints `file:line:column`
findings or JSON, and exits with 1 on errors, so it can gate a CI pipeline.

**VS Code:** checks the whole model the open file belongs to. Small models are checked as you type; big models
(a full vehicle) on save or on request, with a progress count and a closing summary. It must never make the editor
slower: opening a file stays within 10 % or 20 ms of opening it without deckcheck, measured on a 1 GB vehicle model.
Once a model is checked, it can be navigated across its include files: hover a field for its name and what its id
refers to, go to a definition, find every reference, browse the outline, and show field names inline. See the
[user manual](manual/README.md).

**How it is checked:** every error-or-warning decision was made by running LS-DYNA on a test deck for that pattern.
Releases must give zero unexplained findings on the public test models (the LS-DYNA documentation examples, the VIVA+
human body model and the CCSA Toyota Yaris) and catch every planted mistake in more than 80 small test decks.

## Next

- **More required references:** blank or 0 references in solids, beams and other element and part keywords, each
  confirmed against LS-DYNA first.
- **Notepad++:** a tested recipe for running the command line from Notepad++ and jumping to the findings.

## Later

- **M3, AI assistant interface:** an MCP server that lets an AI assistant check a deck, look up a keyword's fields,
  find references and change a field. A change is refused if it would add an error.
- **M4, model-quality checks:** values that overflow their fixed-width field, and checks of the kind a senior
  reviewer makes. Also: suppressing a single finding on purpose.
- **M5, model tree and deck diff.**
- **M6, OpenRadioss.**
- **M7, rule packs** for team conventions, such as a placeholder material that is always kept on purpose.

## Not planned

- Running the solver, or judging results.
- Physics checks before M4: units, time step, contact settings and material sanity are out of scope until then,
  because they are the easiest to get wrong, and a false alarm costs more trust than a missed one.
- Editing or reformatting decks, apart from M3's single-field changes.

## How priorities are set

- **No false alarms.** A linter that cries wolf gets switched off. When deckcheck can't be sure, it says what it
  didn't check instead of guessing.
- **LS-DYNA is the referee.** Whether a pattern is an error or a warning is decided by running LS-DYNA on a test
  deck for it.
- **Do no harm.** The editor must never get slower because deckcheck is installed; every release is measured.
- **Real use decides the order.** Hands-on trials by analysts have changed the plan before (the progress count and
  the closing summary came from one) and will again.
