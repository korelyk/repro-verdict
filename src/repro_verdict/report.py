"""Rendering the verification result as a Markdown report."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from .models import Comparison, Grade, Verdict
from .plan import Plan
from .reviewers import Review, summarise


def _fmt(value: float | None, digits: int = 6) -> str:
    if value is None:
        return "-"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.{digits}g}"


def _rel(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.3f}%"


def environment_card(plan: Plan | None) -> str:
    """Render the machine/data environment as a bullet list."""

    if plan is None or not plan.environment:
        return "_not recorded_"
    lines = []
    for key, value in plan.environment.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def metric_table(comparisons: Sequence[Comparison]) -> str:
    header = "| metric | group | claimed | observed | Δ | Δ% | unit | grade | reason |"
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [header, rule]
    for comparison in comparisons:
        claim = comparison.claim
        rows.append(
            "| {key} | {group} | {claimed} | {observed} | {abs_err} | {rel_err} | {unit} | {grade} | {reason} |".format(
                key=claim.key,
                group=claim.group or "-",
                claimed=_fmt(claim.claimed),
                observed=_fmt(comparison.observed),
                abs_err=_fmt(comparison.abs_err),
                rel_err=_rel(comparison.rel_err),
                unit=claim.unit or "-",
                grade=f"**{comparison.grade.value}**",
                reason=comparison.reason,
            )
        )
    return "\n".join(rows)


def trend_table(verdict: Verdict) -> str:
    if not verdict.trends:
        return "_no multi-group metrics to compare_"
    rows = ["| metric | groups | n | Spearman ρ | ordering consistent |", "| --- | --- | --- | --- | --- |"]
    for trend in verdict.trends:
        consistency = "-" if trend.consistent is None else ("yes" if trend.consistent else "**no**")
        rows.append(
            f"| {trend.key} | {', '.join(trend.groups)} | {trend.n} | {_fmt(trend.rho, 3)} | {consistency} |"
        )
    return "\n".join(rows)


def requirement_table(verdict: Verdict) -> str:
    """Render the requirement tree with the weight each leaf carried."""

    if not verdict.requirement_outcomes:
        return "_no requirement tree declared (only numeric claims were checked)_"
    rows = [
        "| requirement | kind | effective weight | met | evidence / reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for outcome in verdict.requirement_outcomes:
        requirement = outcome.requirement
        met = "-" if outcome.passed is None else ("yes" if outcome.passed else "**no**")
        detail = requirement.evidence or outcome.reason
        rows.append(
            f"| {requirement.id} | {requirement.kind.value} | {outcome.weight:g} | {met} | {detail} |"
        )
    return "\n".join(rows)


def gap_table(verdict: Verdict) -> str:
    if not verdict.gaps:
        return "_none declared_"
    rows = ["| gap | what is missing | affects | resolution used |", "| --- | --- | --- | --- |"]
    for gap in verdict.gaps:
        affects = ", ".join(gap.affects) or "-"
        resolution = gap.resolved_by or gap.default or "-"
        rows.append(f"| {gap.id} | {gap.text} | {affects} | {resolution} |")
    return "\n".join(rows)


def review_sections(reviews: Sequence[Review]) -> str:
    if not reviews:
        return "_review panel not run_"

    panel = summarise(reviews)
    chunks: list[str] = [f"Panel validity: **{panel.describe()}**"]
    if panel.mean_score is not None:
        chunks.append(f"Panel mean score: **{panel.mean_score:g}/10**")
    if panel.failed:
        chunks.append(f"Failed or unparseable: `{', '.join(panel.failed)}`")
    chunks.append("")

    for review in reviews:
        heading = f"### {review.title}"
        if review.error:
            chunks.append(f"{heading}\n\n**failed:** `{review.error}`")
            continue

        badges = []
        if review.score is not None:
            badges.append(f"**{review.score:g}/10**")
        if review.decision:
            badges.append(review.decision)
        chunks.append(f"{heading} — {' · '.join(badges) if badges else 'no score'}\n")

        if review.thought:
            chunks.append(f"> {review.thought.strip()}\n")

        findings = review.payload.get("Findings")
        if isinstance(findings, list) and findings:
            chunks.append("**Findings**\n")
            chunks.append("| location | severity | issue |")
            chunks.append("| --- | --- | --- |")
            for item in findings:
                if isinstance(item, dict):
                    location = item.get("location", "-")
                    severity = item.get("severity", "-")
                    issue = str(item.get("issue", "")).replace("|", "\\|")
                    chunks.append(f"| {location} | {severity} | {issue} |")
                else:
                    chunks.append(f"| - | - | {item} |")
            chunks.append("")

        questions = review.payload.get("Questions")
        if isinstance(questions, list) and questions:
            chunks.append("**Open questions**\n")
            chunks.extend(f"- {item}" for item in questions)
            chunks.append("")

        if review.payload:
            body = "\n".join(
                f"{key}: {value}"
                for key, value in review.payload.items()
                if key not in {"Findings", "Weaknesses", "Questions"}
            )
            chunks.append("<details><summary>full review JSON</summary>\n")
            chunks.append("```\n" + body + "\n```\n")
            chunks.append("</details>")

    return "\n".join(chunks)


def render_report(
    verdict: Verdict,
    *,
    plan: Plan | None = None,
    reviews: Sequence[Review] | None = None,
    generated_at: datetime | None = None,
    target_grade: str | None = None,
) -> str:
    """Render the full acceptance report."""

    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    title = (plan.title if plan and plan.title else "Reproduction verdict")
    paper = plan.paper if plan else ""
    target = target_grade or (plan.target_grade if plan else "") or ""

    counts = verdict.grade_counts
    summary = ", ".join(f"{grade}: {counts.get(grade, 0)}" for grade in ("A", "B", "C", "F"))

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if paper:
        lines.append(f"`{paper}`")
        lines.append("")
    lines.append(f"**Overall grade: {verdict.grade.value}** ({verdict.grade.label}) — {summary}")
    if verdict.score is not None:
        lines.append(
            f"Requirement coverage: **{verdict.score * 100:.1f}%** "
            f"({len(verdict.covered)}/{len(verdict.requirement_outcomes)} leaves earned)"
        )
    if target:
        try:
            met = "met" if verdict.grade.rank >= Grade(target.upper()).rank else "**not met**"
        except ValueError:
            met = "unrecognised"
        lines.append(f"Target grade: {target.upper()} — {met}")
    lines.append(f"Generated: {stamp}")
    lines.append("")

    lines.append("## 1. Metric comparison")
    lines.append("")
    lines.append(metric_table(verdict.comparisons))
    lines.append("")

    lines.append("## 2. Ordering consistency")
    lines.append("")
    lines.append(trend_table(verdict))
    lines.append("")

    lines.append("## 3. Requirement coverage")
    lines.append("")
    lines.append(requirement_table(verdict))
    lines.append("")
    if verdict.gate_warnings:
        lines.append("**Gate warnings — the numeric grade and the tree disagree**")
        lines.append("")
        lines.extend(f"- {warning}" for warning in verdict.gate_warnings)
        lines.append("")

    lines.append("## 4. Gaps")
    lines.append("")
    lines.append(gap_table(verdict))
    lines.append("")
    if verdict.missing:
        lines.append("**Claims with no observation**")
        lines.extend(f"- `{item}`" for item in verdict.missing)
        lines.append("")
    if verdict.stale:
        lines.append("**Refused as stale (produced before the plan was frozen)**")
        lines.extend(f"- `{item}`" for item in verdict.stale)
        lines.append("")
    if verdict.unclaimed:
        lines.append("**Observations with no claim in the plan**")
        lines.extend(f"- `{item}`" for item in verdict.unclaimed)
        lines.append("")
    if not verdict.missing and not verdict.unclaimed and not verdict.stale and not verdict.gaps:
        lines.append("_none recorded_")
        lines.append("")

    lines.append("## 5. Reviewer panel")
    lines.append("")
    lines.append(review_sections(list(reviews or [])))
    lines.append("")

    lines.append("## 6. Environment card")
    lines.append("")
    lines.append(environment_card(plan))
    lines.append("")

    if plan and plan.notes:
        lines.append("## 7. Notes")
        lines.append("")
        lines.extend(f"- {note}" for note in plan.notes)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_review_context(verdict: Verdict, plan: Plan | None = None) -> str:
    """Assemble the deterministic findings into a prompt for the reviewer panel."""

    lines: list[str] = []
    if plan:
        lines.append(f"Paper: {plan.paper or 'unnamed'}")
        if plan.title:
            lines.append(f"Title: {plan.title}")
        if plan.target_grade:
            lines.append(f"Declared target grade: {plan.target_grade}")
        lines.append("")

    lines.append(f"Deterministic overall grade: {verdict.grade.value} ({verdict.grade.label})")
    lines.append(f"Tolerances: A <= {verdict.tolerances.a:g} relative, B <= {verdict.tolerances.b:g} relative")
    if verdict.score is not None:
        lines.append(f"Requirement coverage: {verdict.score * 100:.1f}%")
    lines.append("")
    lines.append("Metric comparison:")
    lines.append(metric_table(verdict.comparisons))
    lines.append("")
    lines.append("Ordering consistency across groups:")
    lines.append(trend_table(verdict))
    lines.append("")
    lines.append("Requirement tree:")
    lines.append(requirement_table(verdict))
    lines.append("")

    if verdict.missing:
        lines.append("Claims with no observation: " + ", ".join(verdict.missing))
    if verdict.stale:
        lines.append("Refused as stale: " + ", ".join(verdict.stale))
    if verdict.unclaimed:
        lines.append("Observations with no claim: " + ", ".join(verdict.unclaimed))
    if verdict.gaps:
        lines.append("")
        lines.append("Gaps declared by the reproducer:")
        lines.append(gap_table(verdict))

    lines.append("")
    lines.append("Environment:")
    lines.append(environment_card(plan))

    if plan and plan.notes:
        lines.append("")
        lines.append("Reproducer notes:")
        lines.extend(f"- {note}" for note in plan.notes)

    if plan and plan.judge_notes:
        lines.append("")
        lines.append("Judge-only notes (not shown to the reproducer):")
        lines.extend(f"- {note}" for note in plan.judge_notes)

    return "\n".join(lines)
