# Corpus terms

What each external test-deck source allows, as read on the date given. External decks are never committed;
`tests/corpus/manifest.toml` records only URL, sha256 and these terms.

| Source | Tier | Terms | Read | How used |
|---|---|---|---|---|
| LS-DYNA Suite R16.1 Student, `documentation/` (examples, benchmarks, guidelines, tutorials) | 1 | Installed under the Ansys clickwrap license Chintan accepted on 2026-09-11. | 2026-10-28 | Read in place on this machine (`in_place = true`); never copied, committed or redistributed. Machine-specific: the corpus job skips them where the install is absent. |
| VIVA+ v2.0.2 (openvt.eu project 171) | 2 | LGPL v3 — `LICENSE.md` and `model/LICENSE/lgpl-3.0.txt` in the archive; vivaplus.readthedocs.io states "openly available under the LGPL v3 license". | 2026-10-28 | Downloaded at test time into `.corpus/` (gitignored). Archive sha256 stable across two downloads. |
| dynaexamples.com | — | Not read: HTTP 503 on 2026-10-28 (twice). | — | Replaced by the install's own documentation decks above (same publisher, Ansys/LST). |
| CCSA/NCAC vehicle models (ccsa.gmu.edu) | 2 | Not read: the site's TLS certificate was rejected from this machine on 2026-10-28. | — | Pending: Chintan to download one model by hand; it then enters as a local `in_place` entry. |
