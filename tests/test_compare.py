import pytest

from repro_verdict import Claim, Grade, Observation, Tolerances, compare_claims, grade_pair, spearman


def claim(key="rmse", claimed=100.0, group="A1"):
    return Claim(key=key, claimed=claimed, group=group)


def obs(key="rmse", observed=100.0, group="A1"):
    return Observation(key=key, observed=observed, group=group)


def test_exact_match_is_grade_a():
    verdict = compare_claims([claim()], [obs()])
    assert verdict.grade is Grade.A
    assert verdict.comparisons[0].rel_err == 0.0


def test_small_deviation_is_grade_a_within_strict_tolerance():
    verdict = compare_claims([claim()], [obs(observed=100.05)], Tolerances(a=0.001, b=0.05))
    assert verdict.grade is Grade.A


def test_deviation_inside_relaxed_tolerance_is_grade_b():
    verdict = compare_claims([claim()], [obs(observed=101.0)], Tolerances(a=0.001, b=0.05))
    assert verdict.grade is Grade.B
    assert verdict.comparisons[0].abs_err == pytest.approx(1.0)


def test_deviation_outside_relaxed_tolerance_is_grade_f():
    verdict = compare_claims([claim()], [obs(observed=140.0)], Tolerances(a=0.001, b=0.05))
    assert verdict.grade is Grade.F


def test_missing_observation_is_grade_f_and_listed():
    verdict = compare_claims([claim()], [])
    assert verdict.grade is Grade.F
    assert verdict.missing == ["rmse@A1"]


def test_observation_present_but_null_is_treated_as_missing():
    verdict = compare_claims([claim()], [Observation(key="rmse", group="A1", observed=None)])
    assert verdict.grade is Grade.F
    assert verdict.missing == ["rmse@A1"]


def test_claim_without_value_is_grade_c():
    verdict = compare_claims([Claim(key="runtime", group="A1")], [Observation(key="runtime", group="A1", observed=42.0)])
    assert verdict.grade is Grade.C


def test_overall_grade_is_the_worst_of_all_metrics():
    claims = [claim(key="rmse", group="A1"), claim(key="mape", claimed=10.0, group="A1")]
    observations = [obs(key="rmse", group="A1"), obs(key="mape", observed=30.0, group="A1")]
    verdict = compare_claims(claims, observations)
    assert verdict.grade is Grade.F
    assert verdict.grade_counts == {"A": 1, "F": 1}


def test_zero_claim_falls_back_to_absolute_error():
    grade, abs_err, rel_err, _ = grade_pair(0.0, 0.0, Tolerances())
    assert grade is Grade.A and abs_err == 0.0 and rel_err == 0.0
    grade, abs_err, rel_err, _ = grade_pair(0.0, 1.0, Tolerances(a=0.1, b=0.5))
    assert grade is Grade.F and abs_err == 1.0 and rel_err == 1.0


def test_tolerances_reject_inverted_bounds():
    with pytest.raises(ValueError):
        Tolerances(a=0.5, b=0.1)
    with pytest.raises(ValueError):
        Tolerances(a=-1.0, b=0.1)


def test_unclaimed_observations_are_reported():
    verdict = compare_claims([claim()], [obs(), Observation(key="extra", group="A1", observed=1.0)])
    assert verdict.unclaimed == ["extra@A1"]


def test_group_is_used_to_join_claims_and_observations():
    claims = [claim(group="A1"), claim(group="A8")]
    observations = [obs(group="A8"), obs(group="A1")]
    verdict = compare_claims(claims, observations)
    assert verdict.grade is Grade.A
    assert [c.id for c in verdict.comparisons] == ["rmse@A1", "rmse@A8"]


def test_spearman_perfect_and_inverted():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 1]) is None


def test_trend_flag_detects_order_preservation():
    claims = [claim(group=g, claimed=v) for g, v in zip("A1 A2 A4 A8".split(), [284.83, 193.58, 221.36, 162.84])]
    same_order = [obs(group=g, observed=v) for g, v in zip("A1 A2 A4 A8".split(), [284.40, 193.59, 221.00, 162.64])]
    inverted = [obs(group=g, observed=v) for g, v in zip("A1 A2 A4 A8".split(), [162.64, 221.00, 193.59, 284.40])]

    kept = compare_claims(claims, same_order)
    flipped = compare_claims(claims, inverted)

    assert kept.trends[0].consistent is True
    assert flipped.trends[0].consistent is False


def test_trend_is_undefined_below_min_groups():
    verdict = compare_claims([claim(group="A1")], [obs(group="A1")])
    assert verdict.trends[0].consistent is None
    assert verdict.trends[0].n == 1
