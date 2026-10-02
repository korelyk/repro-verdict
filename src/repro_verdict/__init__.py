"""repro-verdict: auditable acceptance checking for paper reproduction.

The package separates two questions that are usually mixed together:

1. *Did the numbers match?*  Deterministic, handled by :mod:`repro_verdict.compare`.
2. *Is the reproduction trustworthy?*  Judgement work, handled by the role-based
   reviewer panel in :mod:`repro_verdict.reviewers`.
"""

from .compare import compare_claims, grade_pair, spearman
from .models import Claim, Comparison, Grade, Observation, Tolerances, TrendResult, Verdict

__all__ = [
    "Claim",
    "Comparison",
    "Grade",
    "Observation",
    "Tolerances",
    "TrendResult",
    "Verdict",
    "compare_claims",
    "grade_pair",
    "spearman",
]

__version__ = "0.1.0"
