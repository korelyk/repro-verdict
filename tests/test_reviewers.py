import json

import pytest

from repro_verdict.reviewers import REVIEWERS, get_specs, parse_review, score_review
from repro_verdict.reviewers import Review, summarise


def test_parse_review_reads_thought_and_fenced_json():
    text = """THOUGHT:
The claimed RMSE differs by 0.15 percent, so ordering survives but magnitude drifts.

REVIEW JSON:
```json
{"Overall": 7, "Verdict": "Partially faithful", "Weaknesses": ["no seed sweep"]}
```
"""
    thought, payload = parse_review(text)
    assert thought.startswith("The claimed RMSE")
    assert payload["Overall"] == 7
    assert payload["Weaknesses"] == ["no seed sweep"]


def test_parse_review_falls_back_to_bare_json():
    thought, payload = parse_review('THOUGHT:\nlooks fine\n\n{"Overall": 9, "Verdict": "Faithful"}')
    assert payload["Overall"] == 9
    assert thought == "looks fine"


def test_parse_review_returns_empty_payload_when_unparseable():
    thought, payload = parse_review("THOUGHT:\nnothing structured here")
    assert payload == {}
    assert thought == "nothing structured here"


def test_score_review_normalises_each_dimension_to_its_own_scale():
    spec = REVIEWERS["evidence"]
    payload = {
        "Numerical Agreement": 4,
        "Baseline Rigour": 4,
        "Ablation Completeness": 4,
        "Statistical Care": 4,
        "Overall": 10,
    }
    assert score_review(spec, payload) == pytest.approx(10.0)

    floor = {key: 1 for key in payload}
    weights = spec.scored_fields()
    expected = sum(w * (1 / spec.dimensions[name][0]) for name, w in weights.items()) / sum(weights.values()) * 10
    assert score_review(spec, floor) == pytest.approx(expected, abs=0.005)
    assert 2.0 < expected < 2.1


def test_score_review_ignores_missing_and_unknown_fields():
    spec = REVIEWERS["fidelity"]
    assert score_review(spec, {}) is None
    assert score_review(spec, {"Overall": 5, "Nonexistent": 4}) == pytest.approx(5.0)


def test_score_review_handles_string_numbers():
    spec = REVIEWERS["reproducibility"]
    assert score_review(spec, {"Overall": "8"}) == pytest.approx(8.0)


def test_get_specs_defaults_to_the_full_panel():
    assert [spec.key for spec in get_specs()] == ["fidelity", "evidence", "reproducibility"]


def test_get_specs_selects_and_normalises_names():
    assert [spec.key for spec in get_specs(["EVIDENCE"])] == ["evidence"]


def test_get_specs_rejects_unknown_reviewer():
    with pytest.raises(KeyError):
        get_specs(["referee"])


def test_every_reviewer_form_requests_its_decision_field():
    for spec in REVIEWERS.values():
        form = spec.form()
        assert spec.decision_label in form
        assert "Confidence" in form
        assert all(name in form for name in spec.dimensions)


def test_system_prompt_embeds_persona_and_template():
    prompt = REVIEWERS["fidelity"].system_prompt()
    assert "meticulous methods reviewer" in prompt
    assert "THOUGHT:" in prompt
    assert "REVIEW JSON" in prompt


def test_form_requests_located_findings_with_severity():
    form = REVIEWERS["evidence"].form()
    assert "Findings" in form
    assert "location" in form
    assert "severity" in form
    assert "high" in form and "low" in form


def test_summarise_counts_only_parseable_scores():
    reviews = [
        Review(reviewer="fidelity", title="F", score=5.5, decision="Partially faithful"),
        Review(reviewer="evidence", title="E", score=6.0, decision="Weakly supported"),
        Review(reviewer="reproducibility", title="R", error="boom"),
    ]
    summary = summarise(reviews)
    assert summary.total == 3
    assert summary.valid == 2
    assert summary.mean_score == 5.75
    assert summary.failed == ["reproducibility"]
    assert summary.complete is False
    assert "2/3" in summary.describe()


def test_summarise_reports_a_complete_panel():
    reviews = [Review(reviewer="fidelity", title="F", score=8.0)]
    summary = summarise(reviews)
    assert summary.complete is True
    assert summary.failed == []


def test_summarise_on_an_empty_panel_is_not_complete():
    summary = summarise([])
    assert summary.total == 0
    assert summary.mean_score is None
    assert summary.complete is False
