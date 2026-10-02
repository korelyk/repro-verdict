"""Core data model for reproduction verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Grade(str, Enum):
    """Reproduction grade, ordered best to worst: ``A`` > ``B`` > ``C`` > ``F``.

    ``A``
        Observation matches the claimed number inside the strict tolerance.
    ``B``
        Observation matches inside the relaxed tolerance (same magnitude).
    ``C``
        Nothing was claimed for this entry, but a number was produced, so the
        pipeline demonstrably runs end to end.
    ``F``
        The observation is missing, or it falls outside the relaxed tolerance.
    """

    A = "A"
    B = "B"
    C = "C"
    F = "F"

    @property
    def rank(self) -> int:
        return _GRADE_RANK[self]

    @property
    def label(self) -> str:
        return _GRADE_LABEL[self]

    @classmethod
    def worst(cls, grades: Iterable["Grade"]) -> "Grade":
        """Return the weakest grade in ``grades`` (``F`` beats ``C`` beats ``B`` beats ``A``)."""

        items = list(grades)
        if not items:
            return cls.F
        return min(items, key=lambda grade: grade.rank)


_GRADE_RANK = {Grade.A: 3, Grade.B: 2, Grade.C: 1, Grade.F: 0}
_GRADE_LABEL = {
    Grade.A: "numerically identical",
    Grade.B: "same magnitude / ordering",
    Grade.C: "runs, no numeric target",
    Grade.F: "out of tolerance or missing",
}


@dataclass(frozen=True)
class Claim:
    """A number the paper claims, identified by ``key`` and optional ``group``."""

    key: str
    claimed: float | None = None
    group: str = ""
    unit: str = ""
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.key}@{self.group}" if self.group else self.key


@dataclass(frozen=True)
class Observation:
    """A number your run actually produced, joined to a claim by ``id``."""

    key: str
    observed: float | None = None
    group: str = ""
    unit: str = ""
    source: str = ""

    @property
    def id(self) -> str:
        return f"{self.key}@{self.group}" if self.group else self.key


@dataclass(frozen=True)
class Tolerances:
    """Relative tolerances that translate a deviation into a grade."""

    a: float = 0.001
    b: float = 0.05

    def __post_init__(self) -> None:
        if self.a < 0 or self.b < 0:
            raise ValueError("tolerances must be non-negative")
        if self.a > self.b:
            raise ValueError("strict tolerance A must not exceed relaxed tolerance B")


@dataclass
class Comparison:
    """One claim joined with one observation, plus the resulting grade."""

    claim: Claim
    observed: float | None
    abs_err: float | None
    rel_err: float | None
    grade: Grade
    reason: str = ""

    @property
    def id(self) -> str:
        return self.claim.id


@dataclass
class TrendResult:
    """Whether the ordering across groups survives the reproduction."""

    key: str
    n: int
    rho: float | None
    consistent: bool | None
    groups: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    """Aggregate reproduction verdict."""

    grade: Grade
    comparisons: list[Comparison] = field(default_factory=list)
    trends: list[TrendResult] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unclaimed: list[str] = field(default_factory=list)
    tolerances: Tolerances = field(default_factory=Tolerances)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def grade_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for comparison in self.comparisons:
            key = comparison.grade.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def of_grade(self, grade: Grade) -> list[Comparison]:
        return [c for c in self.comparisons if c.grade is grade]
