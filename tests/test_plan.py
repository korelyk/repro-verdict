import json

import pytest

from repro_verdict.plan import PlanError, as_float, parse_observations, parse_plan


PLAN = {
    "paper": "10.3390/math12010103",
    "title": "GSA-KELM-KF",
    "target_grade": "B",
    "tolerances": {"A": 0.001, "B": 0.05},
    "claims": [
        {"key": "rmse", "group": "A1", "claimed": 284.83, "unit": "vehs/h"},
        {"key": "rmse", "group": "A8", "claimed": 162.84},
    ],
    "environment": {"gpu": "2x RTX 4090"},
    "gaps": ["GSA iteration count unstated"],
    "notes": ["grid searched KELM parameters"],
}


def test_parse_plan_reads_every_field():
    plan = parse_plan(PLAN)
    assert plan.paper == "10.3390/math12010103"
    assert plan.target_grade == "B"
    assert plan.tolerances.a == 0.001
    assert [c.id for c in plan.claims] == ["rmse@A1", "rmse@A8"]
    assert plan.environment["gpu"] == "2x RTX 4090"
    assert plan.gaps == ["GSA iteration count unstated"]


def test_top_level_claim_without_group_has_plain_id():
    plan = parse_plan({"claims": [{"key": "accuracy", "claimed": 0.9}]})
    assert plan.claims[0].id == "accuracy"


def test_missing_claim_key_is_rejected():
    with pytest.raises(PlanError):
        parse_plan({"claims": [{"claimed": 1.0}]})


def test_non_mapping_plan_is_rejected():
    with pytest.raises(PlanError):
        parse_plan(["not", "a", "mapping"])


def test_default_tolerances_when_absent():
    plan = parse_plan({"claims": []})
    assert (plan.tolerances.a, plan.tolerances.b) == (0.001, 0.05)


def test_as_float_accepts_strings_and_rejects_booleans():
    assert as_float(" 12.5 ") == 12.5
    assert as_float("") is None
    assert as_float(None) is None
    with pytest.raises(PlanError):
        as_float(True)
    with pytest.raises(PlanError):
        as_float("abc")


def test_parse_observations_accepts_bare_list_and_value_alias():
    from_list = parse_observations([{"key": "rmse", "group": "A1", "value": 284.4}])
    assert from_list[0].observed == 284.4

    from_doc = parse_observations({"metrics": [{"key": "rmse", "observed": 1.0}]})
    assert from_doc[0].observed == 1.0


def test_parse_observations_rejects_bad_entries():
    with pytest.raises(PlanError):
        parse_observations({"metrics": [{"observed": 1.0}]})
