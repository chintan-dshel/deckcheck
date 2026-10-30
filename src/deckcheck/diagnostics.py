"""What a check reports (spec §4, diagnostics row). Columns are 0-based, end exclusive, as the index stores them;
front doors convert. Coverage (what was not checked) is kept apart from diagnostics: it is never a finding (§5)."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Related:
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    line: int
    start: int
    end: int
    severity: str  # "error" | "warning"
    code: str
    message: str
    related: tuple[Related, ...] = ()


@dataclass(frozen=True)
class NotChecked:
    what: str                 # e.g. "references to MAT (DC001, DC006)"
    reasons: tuple[str, ...]  # the first few, each "file:line why"
    count: int                # how many places in all


@dataclass
class Report:
    main: Path
    diagnostics: list[Diagnostic]
    not_checked: list[NotChecked]
