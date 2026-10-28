# M0 observations

Running record of what the bake-off measured. Evidence: `bakeoff/results/*.jsonl`.

## Torture tier (2026-10-28, dynars 1.1.0)

| Case | dynars | LS-DYNA R16.1 Student | Verdict |
|---|---|---|---|
| include_path | `include_missing` Error: `mat.k` "missing" | reads it via `*INCLUDE_PATH`, normal termination | dynars false alarm: ignores `*INCLUDE_PATH` |
| long_format | `references_resolve` Error: Material 1 not defined | reads `*MAT_ELASTIC +` (long format), normal termination | dynars false alarm: does not parse the `+` long-format suffix, so the material is lost |
| tabs | `references_resolve` Error: Material 1 not defined | Error 10133: material 1 does not exist | agree: both misread the tab-separated card |
| base, comments, crlf, free_format, latin1, lowercase, parameter | no findings | normal termination | agree |
| seeded_mistakes | all 5 seeded findings | (intentionally invalid) | agree |

Line accuracy (true keyword line vs dynars):
- `duplicate_ids`, `unreferenced_entities`: correct keyword line.
- `references_resolve`: keyword line + 1 on every case (seeded 5 vs 4; long_format 7 vs 6; tabs 8 vs 7).
- `include_missing`: always line 0.

Round-trip: byte-identical on every clean case, including CRLF and Latin-1. One-field edit (`PART.grav`): `in_place`,
exactly one line changed.

Tooling defect found and fixed: the runner's watchdog measured the Windows venv launcher (4.8 MB) instead of the
interpreter it spawns; it now measures and kills the whole process tree.
