# Changelog

## 0.1.0 (first release)

The command line and the VS Code extension's language server.

**Checks** (each error-or-warning decision made by running LS-DYNA on a test deck for that pattern):
- DC001: references to ids that are never defined; required references left blank or 0 (`*PART` mid and secid,
  `*ELEMENT_SHELL` pid).
- DC002: the same id defined twice (a warning where LS-DYNA accepts it, such as a node repeated at the same place).
- DC003: values of the wrong type for their field, tabs in cards, cards past the end of a keyword, definitions with
  a blank or 0 id.
- DC004: include files that can't be found, and includes that include themselves.
- DC005: materials, sections and hourglass controls nothing refers to.
- DC006: references LS-DYNA accepts without checking, to ids that don't exist.
- A "Not checked" list wherever deckcheck can't see everything a check needs, instead of a guess.

**Command line:** `deckcheck main.k` follows every `*INCLUDE` and `*INCLUDE_PATH`, prints `file:line:column` findings
or JSON (`--format json`), and exits with 1 on errors.

**Language server** (`deckcheck[lsp]`, used by the VS Code extension): whole-model checks, live on small models and
on save or request on big ones; hover, go to definition, find references, outline, field hints and a field ruler.
