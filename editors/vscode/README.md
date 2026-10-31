# deckcheck for VS Code

deckcheck checks keyword decks for LS-DYNA while you edit them. It finds dangling references, duplicate ids,
values that don't fit their field, missing or circular include files, unused materials and sections, and
references that LS-DYNA accepts but ignores. It reads the deck only: it never runs the solver.

Findings appear as squiggles in the deck and in the Problems panel. When you open an include file, deckcheck checks
the whole model it belongs to, so a material defined in another include is not reported as missing.

## Requirements

Python 3.11 or newer. Nothing else: deckcheck and its language server ship inside the extension. deckcheck uses
the `deckcheck.interpreter` setting if set, otherwise the Python extension's interpreter, otherwise `py -3` or
`python3` on your PATH.

## It stays out of your way

- It never takes part in drawing the file, and its work runs in a separate, low-priority process.
- Small models are re-checked as you type; models whose full check takes longer than 2 seconds are checked when you
  open and save them (the status bar says "checks on save").
- Files larger than 20 MB are read from disk instead of being copied out of the editor.
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
