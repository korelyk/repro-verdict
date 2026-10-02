"""Deterministic comparison between claimed numbers and reproduced numbers.

Everything in this module is pure arithmetic: no model calls, no randomness.
That is deliberate, because the acceptance decision has to be auditable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Sequence

from .models import (
    Claim,
    Comparison,
    Gap,
    Grade,
    Observation,
    Requirement,
    Tolerances,
    TrendResult,
    Verdict,
)
from .requirements import coverage, evaluate, gate_warnings


def average_ranks(values: Sequence[float]) -> list[float]:
    """Return 1-based average ranks (ties share the mean of their ranks)."""

    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation. Returns ``None`` when it is undefined."""

    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = average_ranks(xs), average_ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return cov / (dx * dy)


def grade_pair(
    claimed: float | None,
    observed: float | None,
    tolerances: Tolerances,
) -> tuple[Grade, float | None, float | None, str]:
    """Grade a single claim/observation pair.

    Returns ``(grade, absolute_error, relative_error, human_readable_reason)``.
    """

    if observed is None:
        return Grade.F, None, None, "no observation recorded"
    if claimed is None:
        return Grade.C, None, None, "no claimed value; end-to-end run only"

    abs_err = abs(observed - claimed)
    scale = abs(claimed)
    rel_err = abs_err / scale if scale else abs_err

    if rel_err <= tolerances.a:
        return Grade.A, abs_err, rel_err, f"rel. error {rel_err:.3e} <= A tolerance {tolerances.a:g}"
    if rel_err <= tolerances.b:
        return Grade.B, abs_err, rel_err, f"rel. error {rel_err:.3e} <= B tolerance {tolerances.b:g}"
    return Grade.F, abs_err, rel_err, f"rel. error {rel_err:.3e} > B tolerance {tolerances.b:g}"


def compare_claims(
    claims: Iterable[Claim],
    observations: Iterable[Observation],
    tolerances: Tolerances | None = None,
    *,
    trend_min_groups: int = 3,
    trend_min_rho: float = 0.8,
    requirements: Sequence[Requirement] = (),
    gaps: Sequence[Gap] = (),
    frozen_at: datetime | None = None,
    meta: dict | None = None,
) -> Verdict:
    """Join claims with observations by ``id`` and produce an aggregate verdict.

    ``frozen_at`` activates the provenance gate: an observation that claims to
    have been produced before the plan was frozen is refused, because it cannot
    have been produced by this reproduction.
    """

    tol = tolerances or Tolerances()
    claims = list(claims)
    observations = list(observations)
    index = {obs.id: obs for obs in observations}

    comparisons: list[Comparison] = []
    missing: list[str] = []
    stale: list[str] = []

    for claim in claims:
        obs = index.get(claim.id)
        if obs is None:
            comparisons.append(
                Comparison(claim, None, None, None, Grade.F, "no observation found for this claim")
            )
            missing.append(claim.id)
            continue

        if frozen_at is not None and obs.produced_at is not None and obs.produced_at < frozen_at:
            comparisons.append(
                Comparison(
                    claim,
                    obs.observed,
                    None,
                    None,
                    Grade.F,
                    "stale observation: produced "
                    f"{obs.produced_at.isoformat()} before the plan was frozen at {frozen_at.isoformat()}",
                )
            )
            stale.append(claim.id)
            continue

        grade, abs_err, rel_err, reason = grade_pair(claim.claimed, obs.observed, tol)
        if grade is Grade.F and obs.observed is None:
            missing.append(claim.id)

        if grade is Grade.F:
            resolver = _resolving_gap(claim.id, gaps)
            if resolver is not None:
                grade = Grade.C
                reason = (
                    f"out of tolerance, but gap '{resolver.id}' declares this claim not "
                    f"hard-failable: {resolver.resolved_by}"
                )

        comparisons.append(Comparison(claim, obs.observed, abs_err, rel_err, grade, reason))

    claimed_ids = {claim.id for claim in claims}
    unclaimed = sorted(obs.id for obs in observations if obs.id not in claimed_ids)

    trends = _trends(comparisons, trend_min_groups, trend_min_rho)
    overall = Grade.worst(c.grade for c in comparisons)

    outcomes = evaluate(list(requirements), comparisons) if requirements else []
    warnings = gate_warnings(outcomes, overall) if outcomes else []

    return Verdict(
        grade=overall,
        comparisons=comparisons,
        trends=trends,
        missing=missing,
        unclaimed=unclaimed,
        tolerances=tol,
        requirements=list(requirements),
        requirement_outcomes=outcomes,
        gaps=list(gaps),
        gate_warnings=warnings,
        stale=stale,
        score=coverage(outcomes) if outcomes else None,
        meta=dict(meta or {}),
    )


def _resolving_gap(claim_id: str, gaps: Sequence[Gap]) -> Gap | None:
    """Return the first gap that declares ``claim_id`` exempt from hard failure."""

    for gap in gaps:
        if gap.resolved_by and claim_id in gap.affects:
            return gap
    return None


def _trends(
    comparisons: Sequence[Comparison],
    min_groups: int,
    min_rho: float,
) -> list[TrendResult]:
    """Ordering consistency per metric key, e.g. RMSE across road sections."""

    buckets: dict[str, list[Comparison]] = defaultdict(list)
    for comparison in comparisons:
        if comparison.claim.group and comparison.observed is not None and comparison.claim.claimed is not None:
            buckets[comparison.claim.key].append(comparison)

    trends: list[TrendResult] = []
    for key, items in sorted(buckets.items()):
        items = sorted(items, key=lambda c: c.claim.group)
        groups = [c.claim.group for c in items]
        if len(items) < min_groups:
            trends.append(TrendResult(key=key, n=len(items), rho=None, consistent=None, groups=groups))
            continue
        rho = spearman([c.claim.claimed for c in items], [c.observed for c in items])
        trends.append(
            TrendResult(
                key=key,
                n=len(items),
                rho=rho,
                consistent=None if rho is None else rho >= min_rho,
                groups=groups,
            )
        )
    return trends
