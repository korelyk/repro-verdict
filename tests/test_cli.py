"""The CLI contract callers depend on: exit codes stay distinguishable.

``0`` reproduction met the target, ``1`` it did not, ``2`` the invocation itself
was wrong (unreadable plan, malformed plan, broken panel). A CI job needs to tell
"the science failed" from "the command failed".
"""

import json

import pytest

from repro_verdict.cli import main

PLAN = "tolerances: {A: 0.001, B: 0.05}\nclaims:\n  - {key: rmse, group: A1, claimed: 100.0}\n"


def write_run(directory, observed, **extra):
    directory.mkdir(parents=True, exist_ok=True)
    metric = {"key": "rmse", "group": "A1", "observed": observed}
    metric.update(extra)
    path = directory / "run.json"
    path.write_text(json.dumps({"metrics": [metric]}), encoding="utf-8")
    return path


def test_missing_plan_file_is_a_usage_error_not_a_failed_reproduction(tmp_path, capsys):
    code = main(["check", "--plan", str(tmp_path / "absent.yaml"), "--runs", str(tmp_path)])

    assert code == 2
    assert "cannot read input" in capsys.readouterr().err


def test_unreadable_runs_path_is_a_usage_error(tmp_path, capsys):
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN, encoding="utf-8")

    code = main(["check", "--plan", str(plan), "--runs", str(tmp_path / "absent")])

    assert code == 2
    assert "run path does not exist" in capsys.readouterr().err


def test_malformed_plan_is_a_usage_error(tmp_path, capsys):
    plan = tmp_path / "plan.yaml"
    plan.write_text("claims: 'not a list'\n", encoding="utf-8")

    code = main(["check", "--plan", str(plan), "--runs", str(tmp_path)])

    assert code == 2
    assert "plan error" in capsys.readouterr().err


def test_meeting_the_target_exits_zero(tmp_path, capsys):
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN, encoding="utf-8")
    write_run(tmp_path / "runs", 100.0)

    code = main(
        ["check", "--plan", str(plan), "--runs", str(tmp_path / "runs"),
         "--target-grade", "A", "--out", "-", "--quiet"]
    )

    assert code == 0
    capsys.readouterr()


def test_missing_the_target_exits_one(tmp_path, capsys):
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN, encoding="utf-8")
    write_run(tmp_path / "runs", 140.0)

    code = main(
        ["check", "--plan", str(plan), "--runs", str(tmp_path / "runs"),
         "--target-grade", "A", "--out", "-", "--quiet"]
    )

    assert code == 1
    capsys.readouterr()


def test_frozen_plan_refuses_runs_without_timestamps(tmp_path, capsys):
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN + 'frozen_at: "2026-10-01T00:00:00Z"\n', encoding="utf-8")
    write_run(tmp_path / "runs", 100.0)

    verdict_path = tmp_path / "verdict.json"
    code = main(
        ["check", "--plan", str(plan), "--runs", str(tmp_path / "runs"),
         "--out", "-", "--json-out", str(verdict_path), "--quiet"]
    )

    assert code == 1
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert payload["grade"] == "F"
    assert payload["stale"] == ["rmse@A1"]
    capsys.readouterr()


def test_timestamped_run_passes_the_frozen_plan(tmp_path, capsys):
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN + 'frozen_at: "2026-10-01T00:00:00Z"\n', encoding="utf-8")
    write_run(tmp_path / "runs", 100.0, produced_at="2026-10-01T12:00:00Z")

    code = main(
        ["check", "--plan", str(plan), "--runs", str(tmp_path / "runs"),
         "--target-grade", "A", "--out", "-", "--quiet"]
    )

    assert code == 0
    capsys.readouterr()