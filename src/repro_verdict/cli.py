"""Command line interface for repro-verdict."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .compare import compare_claims
from .models import Grade, Tolerances, Verdict
from .plan import PlanError, load_observations, load_plan
from .report import build_review_context, render_report
from .reviewers import REVIEWERS, get_specs, run_reviews, summarise


PLAN_TEMPLATE = """\
# Reproduction plan for repro-verdict.
paper: "10.3390/math12010103"
title: "GSA-KELM-KF: A Hybrid Model for Short-Term Traffic Flow Forecasting"

# Lowest grade you would accept. A > B > C.
target_grade: B

# A: relative error must stay below this.  B: below the second number.
tolerances:
  A: 0.001
  B: 0.05

claims:
  - key: rmse
    group: A1
    claimed: 284.83
    unit: vehs/h
  - key: rmse
    group: A2
    claimed: 193.58
    unit: vehs/h
  - key: rmse
    group: A4
    claimed: 221.36
    unit: vehs/h
  - key: rmse
    group: A8
    claimed: 162.84
    unit: vehs/h

# Hand these to the reviewer panel so it judges with your constraints in view.
environment:
  gpu: "2x RTX 4090 24GB"
  cpu: "80 cores"
  python: "3.10 (system, no conda)"
  data: "PeMS sections A1/A2/A4/A8, 2019-09, 5-min"

gaps:
  - "GSA gravitational constant and iteration count are not stated in the paper."

notes:
  - "KELM uses (gamma, sigma) = (0.01, 2.0) after grid search."
"""


def _dump(verdict: Verdict) -> dict[str, Any]:
    return {
        "grade": verdict.grade.value,
        "score": verdict.score,
        "tolerances": {"A": verdict.tolerances.a, "B": verdict.tolerances.b},
        "counts": verdict.grade_counts,
        "comparisons": [
            {
                "id": comparison.id,
                "key": comparison.claim.key,
                "group": comparison.claim.group,
                "claimed": comparison.claim.claimed,
                "observed": comparison.observed,
                "abs_err": comparison.abs_err,
                "rel_err": comparison.rel_err,
                "grade": comparison.grade.value,
                "reason": comparison.reason,
                "unit": comparison.claim.unit,
            }
            for comparison in verdict.comparisons
        ],
        "trends": [
            {
                "key": trend.key,
                "groups": trend.groups,
                "n": trend.n,
                "rho": trend.rho,
                "consistent": trend.consistent,
            }
            for trend in verdict.trends
        ],
        "missing": verdict.missing,
        "unclaimed": verdict.unclaimed,
        "stale": verdict.stale,
        "gate_warnings": verdict.gate_warnings,
        "requirements": [
            {
                "id": outcome.requirement.id,
                "kind": outcome.requirement.kind.value,
                "weight": outcome.weight,
                "passed": outcome.passed,
                "reason": outcome.reason,
            }
            for outcome in verdict.requirement_outcomes
        ],
        "gaps": [
            {
                "id": gap.id,
                "text": gap.text,
                "affects": list(gap.affects),
                "resolved_by": gap.resolved_by,
            }
            for gap in verdict.gaps
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repro-verdict",
        description="Auditable acceptance checking for paper reproduction.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="compare reproduced numbers against a plan")
    check.add_argument("--plan", required=True, help="plan file (.json/.yaml/.yml)")
    check.add_argument("--runs", nargs="+", required=True, help="run files or directories of run files")
    check.add_argument("--out", default="REPRO_REPORT.md", help="markdown report path, '-' for stdout")
    check.add_argument("--json-out", default=None, help="optional machine readable verdict")
    check.add_argument("--tol-a", type=float, default=None, help="override strict tolerance")
    check.add_argument("--tol-b", type=float, default=None, help="override relaxed tolerance")
    check.add_argument("--target-grade", choices=["A", "B", "C"], default=None)
    check.add_argument("--llm", action="store_true", help="also run the reviewer panel")
    check.add_argument("--model", default=os.environ.get("REPRO_VERDICT_MODEL", "gpt-4o-mini"))
    check.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    check.add_argument(
        "--api-key",
        default=os.environ.get("REPRO_VERDICT_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    )
    check.add_argument("--reviewers", default=",".join(REVIEWERS))
    check.add_argument("--context", default=None, help="extra context file for the reviewer panel")
    check.add_argument("--quiet", action="store_true")

    init = sub.add_parser("init", help="write a starter plan file")
    init.add_argument("path", nargs="?", default="repro-plan.yaml")
    init.add_argument("--force", action="store_true")

    selfcheck = sub.add_parser(
        "selfcheck",
        help="run the reviewer panel repeatedly to measure its stability",
    )
    selfcheck.add_argument("--plan", required=True)
    selfcheck.add_argument("--runs", nargs="+", required=True)
    selfcheck.add_argument("--repeat", type=int, default=3)
    selfcheck.add_argument("--temperature", type=float, default=0.7)
    selfcheck.add_argument("--model", default=os.environ.get("REPRO_VERDICT_MODEL", "gpt-4o-mini"))
    selfcheck.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    selfcheck.add_argument(
        "--api-key",
        default=os.environ.get("REPRO_VERDICT_API_KEY") or os.environ.get("OPENAI_API_KEY"),
    )
    selfcheck.add_argument("--reviewers", default=",".join(REVIEWERS))
    selfcheck.add_argument("--json-out", default=None)
    return parser


def cmd_check(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    tolerances = plan.tolerances
    if args.tol_a is not None or args.tol_b is not None:
        tolerances = Tolerances(
            a=args.tol_a if args.tol_a is not None else plan.tolerances.a,
            b=args.tol_b if args.tol_b is not None else plan.tolerances.b,
        )

    observations = load_observations(args.runs)
    verdict = compare_claims(
        plan.claims,
        observations,
        tolerances,
        requirements=plan.requirements,
        gaps=plan.gaps,
        frozen_at=plan.frozen_at,
        meta={"plan": plan.paper},
    )

    reviews = []
    if args.llm:
        extra = ""
        if args.context:
            extra = Path(args.context).read_text(encoding="utf-8")
        reviews = run_reviews(
            build_review_context(verdict, plan),
            model=args.model,
            specs=get_specs([name for name in args.reviewers.split(",") if name.strip()]),
            api_key=args.api_key,
            base_url=args.base_url,
            extra_instructions=extra,
        )

    panel = summarise(reviews) if reviews else None
    if panel is not None and panel.valid == 0:
        print(
            f"error: the reviewer panel produced no usable result ({panel.describe()})",
            file=sys.stderr,
        )
        for review in reviews:
            if review.error:
                print(f"  {review.reviewer}: {review.error}", file=sys.stderr)
        return 2

    target = args.target_grade or plan.target_grade or None
    report = render_report(verdict, plan=plan, reviews=reviews, target_grade=target)

    if args.out == "-":
        sys.stdout.write(report)
    else:
        Path(args.out).write_text(report, encoding="utf-8")
        if not args.quiet:
            print(f"report written to {Path(args.out).resolve()}")

    if args.json_out:
        payload = _dump(verdict)
        if reviews:
            payload["reviews"] = [
                {
                    "reviewer": review.reviewer,
                    "score": review.score,
                    "decision": review.decision,
                    "payload": review.payload,
                    "error": review.error,
                }
                for review in reviews
            ]
        Path(args.json_out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if not args.quiet:
        print(f"overall grade: {verdict.grade.value} ({verdict.grade.label})")
        print("counts: " + ", ".join(f"{g}={verdict.grade_counts.get(g, 0)}" for g in ("A", "B", "C", "F")))
        if verdict.score is not None:
            print(f"requirement coverage: {verdict.score * 100:.1f}%")
        if panel is not None:
            print(f"panel: {panel.describe()}")
            if panel.mean_score is not None:
                print(f"panel mean score: {panel.mean_score:g}/10")

    if target:
        try:
            met = verdict.grade.rank >= Grade(target.upper()).rank
        except ValueError:
            print(f"warning: unknown target grade '{target}'", file=sys.stderr)
            return 0
        if not met and not args.quiet:
            print(f"target {target.upper()} not met", file=sys.stderr)
        return 0 if met else 1
    return 0 if verdict.grade is not Grade.F else 1


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists() and not args.force:
        print(f"{path} already exists, use --force to overwrite", file=sys.stderr)
        return 1
    path.write_text(PLAN_TEMPLATE, encoding="utf-8")
    print(f"wrote starter plan to {path.resolve()}")
    return 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    """Measure whether the panel gives stable answers on identical input.

    This is a *stability* check, not a validity check: a panel can be
    consistently wrong. Validity needs human-labelled expectations, which no
    amount of repetition can substitute for.
    """

    plan = load_plan(args.plan)
    observations = load_observations(args.runs)
    verdict = compare_claims(
        plan.claims,
        observations,
        plan.tolerances,
        requirements=plan.requirements,
        gaps=plan.gaps,
        frozen_at=plan.frozen_at,
    )
    context = build_review_context(verdict, plan)
    specs = get_specs([name for name in args.reviewers.split(",") if name.strip()])

    per_reviewer: dict[str, list] = {spec.key: [] for spec in specs}
    for _ in range(max(1, args.repeat)):
        for review in run_reviews(
            context,
            model=args.model,
            specs=specs,
            api_key=args.api_key,
            base_url=args.base_url,
            temperature=args.temperature,
        ):
            per_reviewer[review.reviewer].append(review)

    print(f"stability over {max(1, args.repeat)} runs at temperature {args.temperature:g}")
    print(f"{'reviewer':<18}{'valid':<8}{'mean':<8}{'stdev':<8}{'agreement':<12}decision")
    payload: dict[str, Any] = {"repeat": args.repeat, "temperature": args.temperature, "reviewers": {}}
    for key, reviews in per_reviewer.items():
        summary = summarise(reviews)
        scores = [review.score for review in reviews if review.score is not None]
        decisions = [review.decision for review in reviews if review.decision]
        stdev = 0.0
        if len(scores) > 1:
            mean = sum(scores) / len(scores)
            stdev = (sum((s - mean) ** 2 for s in scores) / (len(scores) - 1)) ** 0.5
        agreement = "-"
        top = ""
        if decisions:
            counts: dict[str, int] = {}
            for decision in decisions:
                counts[decision] = counts.get(decision, 0) + 1
            top, hits = max(counts.items(), key=lambda item: item[1])
            agreement = f"{hits}/{len(reviews)}"
        mean_text = f"{summary.mean_score:g}" if summary.mean_score is not None else "-"
        print(
            f"{key:<18}{summary.valid}/{summary.total:<6}{mean_text:<8}{stdev:<8.2f}{agreement:<12}{top}"
        )
        payload["reviewers"][key] = {
            "valid": summary.valid,
            "total": summary.total,
            "mean_score": summary.mean_score,
            "stdev": round(stdev, 3),
            "agreement": agreement,
            "decisions": decisions,
        }

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return cmd_check(args)
        if args.command == "init":
            return cmd_init(args)
        if args.command == "selfcheck":
            return cmd_selfcheck(args)
    except OSError as exc:
        print(f"cannot read input: {exc}", file=sys.stderr)
        return 2
    except PlanError as exc:
        print(f"plan error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
