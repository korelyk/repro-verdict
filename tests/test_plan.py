import json

import pytest

from repro_verdict.plan import PlanError, as_float, parse_observations, parse_plan
from repro_verdict.plan import as_datetime, parse_gaps, parse_requirements


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
    assert [gap.text for gap in plan.gaps] == ["GSA iteration count unstated"]
    assert plan.gaps[0].id == "gap-1"


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


def test_requirements_parse_into_a_tree_with_weights_and_attestation():
    tree = parse_requirements(
        [
            {
                "id": "method",
                "text": "the model",
                "weight": 2.0,
                "children": [
                    {"id": "gsa", "text": "search", "kind": "development", "attested": True},
                    {"id": "rmse", "text": "numbers", "claim_ids": ["rmse@A1"]},
                ],
            }
        ]
    )
    root = tree[0]
    assert root.id == "method"
    assert [child.id for child in root.children] == ["gsa", "rmse"]
    assert root.children[0].attested is True
    assert root.children[0].kind.value == "development"
    assert root.children[1].claim_ids == ("rmse@A1",)


def test_requirements_default_kind_is_result():
    tree = parse_requirements([{"id": "x", "text": ""}])
    assert tree[0].kind.value == "result"
    assert tree[0].weight == 1.0


def test_requirements_reject_unknown_kind_and_bad_attestation():
    with pytest.raises(PlanError):
        parse_requirements([{"id": "x", "kind": "vibes"}])
    with pytest.raises(PlanError):
        parse_requirements([{"id": "x", "attested": "yes"}])
    with pytest.raises(PlanError):
        parse_requirements([{"text": "no id"}])


def test_gaps_accept_plain_strings_and_mappings():
    gaps = parse_gaps(["plain text", {"id": "g", "text": "mapped", "affects": ["rmse@A1"]}])
    assert gaps[0].id == "gap-1"
    assert gaps[0].text == "plain text"
    assert gaps[1].affects == ("rmse@A1",)


def test_plan_reads_requirements_gaps_and_freeze_time():
    plan = parse_plan(
        {
            "claims": [],
            "frozen_at": "2026-10-01T00:00:00Z",
            "judge_notes": ["only for the panel"],
            "requirements": [{"id": "r", "text": ""}],
            "gaps": [{"id": "g", "text": "t", "resolved_by": "used defaults"}],
        }
    )
    assert plan.frozen_at is not None and plan.frozen_at.year == 2026
    assert plan.judge_notes == ["only for the panel"]
    assert plan.requirements[0].id == "r"
    assert plan.gaps[0].resolved_by == "used defaults"


def test_freeze_time_accepts_offsets_and_rejects_junk():
    assert as_datetime("2026-10-01T12:00:00+08:00").utcoffset().total_seconds() == 8 * 3600
    assert as_datetime(None) is None
    assert as_datetime("") is None
    with pytest.raises(PlanError):
        as_datetime("last tuesday")


def test_observations_carry_provenance():
    parsed = parse_observations(
        {
            "run_id": "20261001",
            "metrics": [
                {
                    "key": "rmse",
                    "group": "A1",
                    "observed": 1.0,
                    "produced_at": "2026-10-01T09:00:00Z",
                }
            ],
        }
    )
    assert parsed[0].produced_at is not None
    assert parsed[0].run_id == "20261001"
