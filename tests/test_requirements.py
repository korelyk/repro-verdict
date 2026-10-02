import pytest

from repro_verdict import (
    Claim,
    Grade,
    Observation,
    Requirement,
    RequirementKind,
    compare_claims,
    coverage,
)
from repro_verdict.requirements import evaluate, gate_warnings, iter_leaves


def test_iter_leaves_multiplies_weights_down_the_tree():
    tree = Requirement(
        id="root",
        text="",
        weight=2.0,
        children=(
            Requirement(id="a", text="", weight=3.0),
            Requirement(id="b", text="", weight=1.0),
        ),
    )
    weights = {leaf.id: weight for leaf, weight in iter_leaves(tree)}
    assert weights == {"a": 6.0, "b": 2.0}


def test_result_leaf_passes_when_linked_claims_are_within_tolerance():
    claims = [Claim(key="rmse", group="A1", claimed=100.0)]
    observations = [Observation(key="rmse", group="A1", observed=100.0)]
    verdict = compare_claims(claims, observations)
    tree = [Requirement(id="tree", text="", children=(Requirement(id="r", text="", claim_ids=("rmse@A1",)),))]

    outcomes = evaluate(tree, verdict.comparisons)
    assert outcomes[0].passed is True
    assert "A" in outcomes[0].reason


def test_result_leaf_fails_when_a_linked_claim_fails():
    claims = [Claim(key="rmse", group="A1", claimed=100.0)]
    observations = [Observation(key="rmse", group="A1", observed=200.0)]
    verdict = compare_claims(claims, observations)
    tree = [Requirement(id="tree", text="", children=(Requirement(id="r", text="", claim_ids=("rmse@A1",)),))]

    outcomes = evaluate(tree, verdict.comparisons)
    assert outcomes[0].passed is False


def test_result_leaf_without_a_linked_comparison_is_unresolved():
    tree = [Requirement(id="ghost", text="")]
    outcomes = evaluate(tree, [])
    assert outcomes[0].passed is None
    assert "no comparison" in outcomes[0].reason


def test_development_leaf_uses_attestation():
    done = Requirement(id="gsa", text="", kind=RequirementKind.development, attested=True)
    todo = Requirement(id="kf", text="", kind=RequirementKind.development, attested=False)
    unknown = Requirement(id="ablation", text="", kind=RequirementKind.execution)

    outcomes = {o.requirement.id: o for o in evaluate([done, todo, unknown], [])}
    assert outcomes["gsa"].passed is True
    assert outcomes["kf"].passed is False
    assert outcomes["ablation"].passed is None


def test_coverage_is_weighted_and_none_for_empty_input():
    assert coverage([]) is None

    heavy_done = Requirement(
        id="heavy", text="", weight=3.0, kind=RequirementKind.development, attested=True
    )
    light_todo = Requirement(
        id="light", text="", weight=1.0, kind=RequirementKind.development, attested=False
    )
    outcomes = evaluate([heavy_done, light_todo], [])
    assert coverage(outcomes) == pytest.approx(0.75)


def test_unattested_leaves_lower_the_score_without_counting_as_failures():
    unknown = Requirement(id="x", text="", kind=RequirementKind.execution)
    outcomes = evaluate([unknown], [])
    assert outcomes[0].passed is None
    assert coverage(outcomes) == 0.0


def test_gate_warning_fires_when_numbers_pass_but_a_ladder_step_failed():
    outcomes = evaluate(
        [Requirement(id="gsa", text="", kind=RequirementKind.development, attested=False)], []
    )
    warnings = gate_warnings(outcomes, Grade.B)
    assert warnings and "gsa" in warnings[0]

    assert gate_warnings(outcomes, Grade.C) == []
    assert gate_warnings(outcomes, Grade.F) == []


def test_gate_warning_lists_unattested_leaves():
    outcomes = evaluate([Requirement(id="ablation", text="", kind=RequirementKind.execution)], [])
    warnings = gate_warnings(outcomes, Grade.B)
    assert any("not attested" in warning for warning in warnings)


def test_requirements_are_wired_into_the_verdict():
    claims = [Claim(key="rmse", group="A1", claimed=100.0)]
    observations = [Observation(key="rmse", group="A1", observed=100.0)]
    tree = [
        Requirement(
            id="tree",
            text="",
            children=(
                Requirement(id="rmse", text="", claim_ids=("rmse@A1",)),
                Requirement(
                    id="gsa",
                    text="",
                    kind=RequirementKind.development,
                    attested=False,
                    weight=3.0,
                ),
            ),
        )
    ]
    verdict = compare_claims(claims, observations, requirements=tree)

    assert verdict.grade is Grade.A
    assert verdict.score == pytest.approx(0.25)
    assert len(verdict.covered) == 1
    assert len(verdict.uncovered) == 1
    assert verdict.gate_warnings
