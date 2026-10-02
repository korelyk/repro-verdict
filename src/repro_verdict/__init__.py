"""repro-verdict: auditable acceptance checking for paper reproduction.

The package separates two questions that are usually mixed together:

1. *Did the numbers match?*  Deterministic, handled by :mod:`repro_verdict.compare`.
2. *Is the reproduction trustworthy?*  Judgement work, handled by the role-based
   reviewer panel in :mod:`repro_verdict.reviewers`.
"""

from .compare import compare_claims, grade_pair, spearman
from .models import (
    Claim,
    Comparison,
    Gap,
    Grade,
    Observation,
    Requirement,
    RequirementKind,
    RequirementOutcome,
    Tolerances,
    TrendResult,
    Verdict,
)
from .requirements import coverage, evaluate, walk_leaves

__all__ = [
    "Claim",
    "Comparison",
    "Gap",
    "Grade",
    "Observation",
    "Requirement",
    "RequirementKind",
    "RequirementOutcome",
    "Tolerances",
    "TrendResult",
    "Verdict",
    "compare_claims",
    "coverage",
    "evaluate",
    "grade_pair",
    "spearman",
    "walk_leaves",
]

__version__ = "0.2.0"
