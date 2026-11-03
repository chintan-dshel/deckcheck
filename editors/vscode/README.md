# deckcheck for VS Code

deckcheck checks keyword decks for LS-DYNA while you edit them. It finds dangling references, duplicate ids,
values that don't fit their field, missing or circular include files, unused materials and sections, and
references that LS-DYNA accepts but ignores. It reads the deck only: it never runs the solver.

Findings appear as squiggles in the deck and in the Problems panel. When you open an include file, deckcheck checks
the whole model it belongs to, so a material defined in another include is not reported as missing.

## Navigate a model

Once a model has been checked, deckcheck also finds your way around it, across its include files:
- **Hover** a field: its name, columns and type, the value as read, and what an id refers to (`mid → MAT 1,
  *MAT_ELASTIC at mat.k:3`). On a definition, how many uses it has. No descriptions from the keyword manual.
- **Go to Definition** (F12, or Ctrl+click) on an id jumps to what defines it, in whichever include it is.
- **Find All References** (Shift+F12) on an id or its definition lists every use in the model.
- The **Outline** panel lists the file's keywords, each with its id and title.
- **Field names** inline: hold Ctrl+Alt to see each field's name over its value.
- **Insert field ruler**: on a fixed-column card, the lightbulb (Ctrl+.) adds a `$#` comment line naming the
  columns above it.

Navigation answers from the last check and never waits for one. So:
- before a model's first check (a big model: after "click to check"), and in a file edited since its last check,
  there is nothing until the next check. The outline of a file up to 2 MB follows your edits.
- deep in a long list-style block, such as a node set more than 2,000 lines below its keyword, hover shows nothing.
  Node and element tables work at any depth.
- a file with more than 10,000 keywords gets no outline; the panel says why.
- the field ruler is not offered on comma-separated cards, long-format cards, or files larger than 20 MB.

## Requirements

Python 3.11 or newer. Nothing else: deckcheck and its language server ship inside the extension. deckcheck uses
the `deckcheck.interpreter` setting if set, otherwise the Python extension's interpreter, otherwise `py -3` or
`python3` on your PATH.

If you install it while VS Code is open, reload the window once (Command Palette > **Developer: Reload Window**):
an open window doesn't start a newly installed extension. A `.k` file's language, at the bottom right, then reads
**Keyword deck (LS-DYNA)**.

## It stays out of your way

- It never takes part in drawing the file, and its work runs in a separate, low-priority process.
- Small models are re-checked as you type. A big model, one whose full check takes longer than 2 seconds such as a
  full vehicle, is never checked just because you opened it: the status bar says "big model, click to check", and a
  click or a save runs the check. While it runs, it uses background priority, and the status bar counts the seconds
  against an estimate; when it ends, a message says what was checked (files, size, time) and what was found.
  Clicking again while it runs doesn't restart it. After an edit to a big model the status bar says "save to check".
- Files larger than 20 MB are read from disk instead of being copied out of the editor, so a check sees their saved
  version: "Check this model now" offers to save them first.
- If a model needs more memory than its budget (2 GB), deckcheck pauses itself and says so in the status bar.
- The status bar item shows what was not checked and why. Click it to pause deckcheck for the workspace.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `deckcheck.enable` | `true` | Off switch per workspace or folder |
| `deckcheck.exclude` | `[]` | Globs never checked or scanned |
| `deckcheck.mainDecks` | `[]` | Main decks; overrides detection |
| `deckcheck.interpreter` | `""` | Python 3.11+ to run deckcheck |
| `deckcheck.liveThresholdSeconds` | `2` | Live checks below this full-check time |
| `deckcheck.maxSyncMB` | `20` | Larger files are read from disk and checked on save |
| `deckcheck.memoryMB` | `2048` | deckcheck pauses above this |
| `deckcheck.ignore` | `[]` | Codes left out |

Not tested: remote, WSL and Codespaces workspaces.

## License

Apache-2.0; bundled components are listed in `NOTICE`. deckcheck is an independent project, not affiliated with or
endorsed by Ansys. LS-DYNA is a trademark of its owner.
