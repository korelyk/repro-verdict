"""Evaluating the requirement tree.

The tree answers a question the numeric grade cannot: *how much of the
reproduction actually happened?*  A paper may claim four RMSE values, but the
real work behind them is "the GSA search was implemented", "the Kalman filter
runs the way the paper describes", "the ablation table was produced". Those are
not numbers, and a flat claim list cannot hold them.

``development`` -> ``execution`` -> ``result`` is the partial-credit ladder:
code existing is worth something, code that ran is worth more, matching numbers
is worth most. Only ``result`` leaves are graded arithmetically; the other two
are attested by the reproducer and audited by the reviewer panel.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Sequence

from .models import (
    Comparison,
    Grade,
    Requirement,
    RequirementKind,
    RequirementOutcome,
)


def iter_leaves(node: Requirement, prefix: float = 1.0) -> Iterator[tuple[Requirement, float]]:
    """Yield ``(leaf, effective_weight)``, multiplying weights down the tree."""

    weight = prefix * node.weight
    if node.is_leaf:
        yield node, weight
        return
    for child in node.children:
        yield from iter_leaves(child, weight)


def walk_leaves(requirements: Iterable[Requirement]) -> Iterator[Requirement]:
    """Yield every leaf in the forest."""

    for node in requirements:
        if node.is_leaf:
            yield node
        else:
            yield from walk_leaves(node.children)


def _grade_result_leaf(leaf: Requirement, comparisons: Sequence[Comparison]) -> RequirementOutcome:
    index = {comparison.id: comparison for comparison in comparisons}
    linked_ids = list(leaf.claim_ids) or [leaf.id]
    linked = [index[claim_id] for claim_id in linked_ids if claim_id in index]

    if not linked:
        return RequirementOutcome(
            requirement=leaf,
            passed=None,
            reason="no comparison is linked to this requirement",
        )

    failing = [c for c in linked if c.grade is Grade.F]
    if failing:
        detail = "; ".join(f"{c.id}: {c.reason}" for c in failing)
        return RequirementOutcome(requirement=leaf, passed=False, reason=detail)

    worst = min(linked, key=lambda c: c.grade.rank)
    return RequirementOutcome(
        requirement=leaf,
        passed=True,
        reason=f"worst linked grade {worst.grade.value} ({worst.id})",
    )


def evaluate(
    requirements: Sequence[Requirement],
    comparisons: Sequence[Comparison],
) -> list[RequirementOutcome]:
    """Resolve every leaf against the numeric comparisons."""

    outcomes: list[RequirementOutcome] = []
    for root in requirements:
        for leaf, weight in iter_leaves(root):
            if leaf.kind is RequirementKind.result:
                outcome = _grade_result_leaf(leaf, comparisons)
            elif leaf.attested is None:
                outcome = RequirementOutcome(
                    requirement=leaf,
                    passed=None,
                    reason=f"{leaf.kind.value} not attested",
                )
            else:
                outcome = RequirementOutcome(
                    requirement=leaf,
                    passed=leaf.attested,
                    reason="attested by the reproducer" if leaf.attested else "attested as not done",
                )
            outcome.weight = weight
            outcomes.append(outcome)
    return outcomes


def coverage(outcomes: Sequence[RequirementOutcome]) -> float | None:
    """Weighted share of requirements that passed, in ``[0, 1]``.

    Leaves that are merely unattested do not count as failures; they lower the
    score by staying out of the numerator, which is the honest reading.
    """

    total = sum(outcome.weight for outcome in outcomes)
    if not total:
        return None
    earned = sum(outcome.weight for outcome in outcomes if outcome.passed)
    return round(earned / total, 4)


def gate_warnings(outcomes: Sequence[RequirementOutcome], grade: Grade) -> list[str]:
    """Flag places where the numeric grade and the tree disagree.

    This is the "the numbers match but the method was never implemented" case.
    The grade is deliberately *not* changed by it; the disagreement is surfaced
    instead, because silently rewriting the grade would make it unauditable.
    """

    warnings: list[str] = []
    ladder_failures = [
        outcome
        for outcome in outcomes
        if outcome.passed is False
        and outcome.requirement.kind in {RequirementKind.development, RequirementKind.execution}
    ]
    if ladder_failures and grade.rank >= Grade.B.rank:
        for outcome in ladder_failures:
            warnings.append(
                f"numeric grade is {grade.value}, but requirement "
                f"'{outcome.requirement.id}' ({outcome.requirement.kind.value}) is unsatisfied: "
                f"{outcome.reason}"
            )

    unattested = [outcome.requirement.id for outcome in outcomes if outcome.passed is None]
    if unattested:
        warnings.append(
            "not attested, so counted as unearned: " + ", ".join(unattested)
        )
    return warnings
