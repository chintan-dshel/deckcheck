# Changelog

## 0.1.0 (first release)

- Squiggles and the Problems panel for the whole model the open file belongs to, across its include files.
- Small models are checked as you type; a big model (a full vehicle) when you save it or click "big model, click to
  check", with a progress count and a closing summary.
- Navigation once a model is checked: hover a field for its name and what its id refers to, go to definition, find
  every reference, the Outline panel, field names inline (hold Ctrl+Alt), and "Insert field ruler".
- The status bar shows the model of the file in front of you and what was not checked; click it to pause deckcheck
  for the workspace.
- Do no harm, measured on a 1 GB vehicle model: opening a file is at most 10 % or 20 ms slower than without
  deckcheck, and editor commands stay under 100 ms during a full check.
- Needs only Python 3.11 or newer: deckcheck and its language server ship inside the extension.
